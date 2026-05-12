import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import admin as admin_api
from app.api import jobs as jobs_api
from app.core.config import settings
from app.db.engine import init_db
from app.printer.driver import set_active_geometry
from app.printer.worker import worker_loop
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
    running under a Windows service with no console)."""
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


def _calibrate_printer():
    """Probe the printer and push an oversized DEVMODE for edge-to-edge
    prints. Returns (printer_name, devmode_snapshot) for the shutdown
    restore, or None on any failure (we still want the server to boot)."""
    if sys.platform != "win32":
        return None

    target = settings.printer_name
    if not target:
        chosen = _prompt_printer_selection()
        if not chosen:
            return None
        target = chosen
        # Propagate so the worker's print_image() sees the same name.
        settings.printer_name = target

    try:
        from app.printer.calibration import configure_borderless

        geometry, snapshot = configure_borderless(
            target,
            target_long_mm=settings.print_paper_long_mm,
            target_short_mm=settings.print_paper_short_mm,
        )
        set_active_geometry(target, geometry)
        return target, snapshot
    except Exception:
        log.exception("printer calibration failed; falling back to per-job probe")
        return None


def _restore_printer(state) -> None:
    if state is None:
        return
    printer_name, snapshot = state
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
    calibration_state = _calibrate_printer()

    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(worker_loop(stop_event), name="print-worker")
    retention_task = asyncio.create_task(retention_loop(stop_event), name="retention")
    try:
        yield
    finally:
        stop_event.set()
        for task in (worker_task, retention_task):
            try:
                await asyncio.wait_for(task, timeout=10)
            except asyncio.TimeoutError:
                task.cancel()
        _restore_printer(calibration_state)


def create_app() -> FastAPI:
    app = FastAPI(title="print-web", version="0.1.0", lifespan=lifespan)

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
