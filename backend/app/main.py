import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin as admin_api
from app.api import jobs as jobs_api
from app.core.config import settings
from app.db.engine import init_db
from app.printer.driver import set_active_geometry
from app.printer.worker import recover_interrupted, worker_loop
from app.services.retention import retention_loop
from app.spa import mount_spa

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

log = logging.getLogger("app.main")


def _list_installed_printers() -> list[str]:
    if sys.platform != "win32":
        return []
    import win32print

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [p[2] for p in win32print.EnumPrinters(flags)]


def _prompt_printer_selection() -> str | None:
    """Enumerate installed printers and let the operator pick one. Falls
    back to the Windows default printer if we can't read stdin (e.g.,
    running under a Windows service with no console).

    Only used when PRINTER_NAME is empty. Multi-printer setups need to
    list names explicitly in .env — the prompt picks just one to keep
    the boot UI simple.
    """
    names = _list_installed_printers()
    if not names:
        log.warning("no printers installed; skipping calibration")
        return None

    if not (sys.stdin and sys.stdin.isatty()):
        import win32print

        default = win32print.GetDefaultPrinter()
        log.warning(
            "PRINTER_NAME is unset and no TTY is available; "
            "falling back to Windows default printer: %s",
            default,
        )
        return default

    out = sys.stderr  # keep our prompt next to uvicorn's startup logs
    print(file=out)
    print("PRINTER_NAME이 설정되지 않았습니다. 사용할 프린터를 선택하세요:", file=out)
    print("(여러 대를 함께 쓰려면 종료 후 .env에 콤마로 나열하세요.)", file=out)
    for i, name in enumerate(names, start=1):
        print(f"  [{i}] {name}", file=out)
    print(file=out)

    while True:
        try:
            raw = input("선택 번호: ").strip()
        except (EOFError, KeyboardInterrupt):
            log.warning("printer selection cancelled; skipping calibration")
            return None
        try:
            idx = int(raw)
        except ValueError:
            print(f"  1~{len(names)} 사이 숫자를 입력해주세요.", file=out)
            continue
        if 1 <= idx <= len(names):
            chosen = names[idx - 1]
            print(f"  -> 선택됨: {chosen}", file=out)
            return chosen
        print(f"  1~{len(names)} 범위를 벗어났습니다.", file=out)


def _resolve_printer_targets() -> list[str]:
    """Decide which printers the worker pool will serve.

    - PRINTER_NAME set (single or CSV): use those names verbatim.
    - PRINTER_NAME empty + TTY: prompt for one printer, return it.
    - PRINTER_NAME empty + no TTY: return [Windows default].
    """
    names = settings.printer_names
    if names:
        return names
    chosen = _prompt_printer_selection()
    return [chosen] if chosen else []


def _calibrate_one(printer_name: str):
    """Try to push the oversized-paper DEVMODE for one printer.

    Returns the pre-modification snapshot on success (used to restore on
    shutdown), or None if calibration was skipped or failed. A None
    return is recoverable — the worker just falls back to per-job GDI
    probing for that printer, losing only the edge-to-edge trick.
    """
    if sys.platform != "win32":
        return None

    try:
        from app.printer.calibration import configure_borderless

        geometry, snapshot = configure_borderless(
            printer_name,
            target_long_mm=settings.print_paper_long_mm,
            target_short_mm=settings.print_paper_short_mm,
        )
        set_active_geometry(printer_name, geometry)
        return snapshot
    except Exception:
        log.exception(
            "calibration failed for %s; this printer will still print but "
            "without the oversize-paper edge-to-edge trick",
            printer_name,
        )
        return None


def _restore_one(printer_name: str, snapshot) -> None:
    if snapshot is None:
        return
    try:
        from app.printer.calibration import restore_devmode

        restore_devmode(printer_name, snapshot)
        set_active_geometry(printer_name, None)
        log.info("restored DEVMODE for %s", printer_name)
    except Exception:
        log.exception("failed to restore DEVMODE for %s", printer_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    targets = _resolve_printer_targets()
    snapshots: dict[str, object] = {
        name: _calibrate_one(name) for name in targets
    }

    if not targets:
        log.warning(
            "no printers available; APPROVED jobs will accumulate "
            "until a printer is configured"
        )
    else:
        log.info("workers will serve printers: %s", ", ".join(targets))

    # Mark anything still in PRINTING from a previous run as FAILED before
    # workers start picking up new jobs.
    loop = asyncio.get_running_loop()
    recovered = await loop.run_in_executor(None, recover_interrupted)
    if recovered:
        log.warning("recovered %d interrupted job(s) to FAILED", recovered)

    stop_event = asyncio.Event()
    # One shared claim lock serializes the SELECT+UPDATE in _claim_next_job
    # across all workers so two printers can't grab the same row.
    claim_lock = asyncio.Lock()
    worker_tasks = [
        asyncio.create_task(
            worker_loop(stop_event, name, claim_lock),
            name=f"print-worker:{name}",
        )
        for name in targets
    ]
    retention_task = asyncio.create_task(retention_loop(stop_event), name="retention")

    try:
        yield
    finally:
        stop_event.set()
        for task in [*worker_tasks, retention_task]:
            try:
                await asyncio.wait_for(task, timeout=10)
            except asyncio.TimeoutError:
                task.cancel()
        for name, snapshot in snapshots.items():
            _restore_one(name, snapshot)


def create_app() -> FastAPI:
    app = FastAPI(title="print-web", version="0.1.0", lifespan=lifespan)

    # External kiosk front-end hits this API cross-origin. Explicit list
    # (no '*') because the admin endpoints rely on session cookies, which
    # browsers refuse to send unless allow_credentials=True is paired with
    # a concrete origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://phosom-kiosk.pages.dev"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(jobs_api.router)
    app.include_router(admin_api.router)

    # Mount last so all explicit API routes take precedence.
    mount_spa(app)

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
