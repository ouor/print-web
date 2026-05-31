"""Windows GDI printing via pywin32.

Renders a single image to one page, scaled to fit the printable area
with aspect ratio preserved. Uses a startup-cached PrintGeometry when
available (set by app.printer.calibration) so the print fills the real
photo paper edge-to-edge.
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.printer.calibration import PrintGeometry
from app.printer.spool import wait_for_completion

if sys.platform == "win32":
    import win32print
    import win32ui
    from PIL import Image, ImageWin
else:  # pragma: no cover - non-Windows fallback for dev tooling only
    win32print = win32ui = None
    Image = ImageWin = None


# GDI DeviceCaps constants (kept inline to avoid magic numbers further down).
_PHYSICALWIDTH = 110
_PHYSICALHEIGHT = 111
_PHYSICALOFFSETX = 112
_PHYSICALOFFSETY = 113
_HORZRES = 8
_VERTRES = 10


# printer_name → calibrated geometry. Populated by app.main at startup
# for each configured printer; print_image() reads from here so the worker
# doesn't re-probe GDI on every job. Multiple entries when more than one
# printer is configured.
_active: dict[str, PrintGeometry] = {}


def set_active_geometry(printer_name: str, geometry: PrintGeometry | None) -> None:
    """Cache the calibrated geometry for one printer. Pass geometry=None to
    clear the entry (e.g. on shutdown DEVMODE restore)."""
    if geometry is None:
        _active.pop(printer_name, None)
    else:
        _active[printer_name] = geometry


class PrinterError(RuntimeError):
    pass


def resolve_printer_name(configured: str | None) -> str:
    if sys.platform != "win32":
        raise PrinterError("printing is only supported on Windows")
    if configured:
        return configured
    return win32print.GetDefaultPrinter()


def print_image(
    image_path: str | Path,
    printer_name: str | None = None,
    *,
    spool_doc_name: str | None = None,
    spool_timeout_seconds: float = 60.0,
) -> None:
    """Send one image to the printer as a single page and wait for the
    spooler to confirm completion.

    spool_doc_name: the document title used both for StartDoc and for
        matching the job in EnumJobs. Caller should pass a value that's
        unique per print attempt (e.g. f"print-web:{job_id}") so the
        spool tracker can lock onto exactly our job.

    Raises PrinterError on failure (GDI error, spooler-reported error,
    or timeout waiting for PRINTED).
    """
    if sys.platform != "win32":
        raise PrinterError("printing is only supported on Windows")

    target = resolve_printer_name(printer_name)
    path = Path(image_path)
    if not path.exists():
        raise PrinterError(f"image not found: {path}")

    doc_name = spool_doc_name or f"print-web: {path.name}"

    hdc = win32ui.CreateDC()
    try:
        hdc.CreatePrinterDC(target)
    except Exception as e:  # pragma: no cover - depends on installed drivers
        raise PrinterError(f"could not open printer '{target}': {e}") from e

    try:
        # Prefer the geometry the lifespan probed at startup so we don't
        # re-query GDI on every job. Falls back to a per-call probe if
        # calibration was skipped (or this printer wasn't in the configured
        # set, e.g. fell back to Windows default).
        cached = _active.get(target)
        if cached is not None:
            content_w = cached.content_w_px
            content_h = cached.content_h_px
        else:
            content_w = hdc.GetDeviceCaps(_HORZRES)
            content_h = hdc.GetDeviceCaps(_VERTRES)

        with Image.open(path) as im:
            im.load()
            img_w, img_h = im.size
            scale = min(content_w / img_w, content_h / img_h)
            draw_w = int(img_w * scale)
            draw_h = int(img_h * scale)
            # Center within the printable (content) area. GDI puts the
            # drawing origin at the printable top-left, so we don't need
            # to compensate for PHYSICALOFFSET here.
            x = (content_w - draw_w) // 2
            y = (content_h - draw_h) // 2

            hdc.StartDoc(doc_name)
            try:
                hdc.StartPage()
                dib = ImageWin.Dib(im)
                dib.draw(hdc.GetHandleOutput(), (x, y, x + draw_w, y + draw_h))
                hdc.EndPage()
                hdc.EndDoc()
            except Exception as e:
                try:
                    hdc.AbortDoc()
                except Exception:
                    pass
                raise PrinterError(f"print job aborted: {e}") from e
    finally:
        try:
            hdc.DeleteDC()
        except Exception:
            pass

    # GDI returned cleanly — the job is now in the spooler queue. Wait for
    # the spooler to actually print it (or fail) so DONE means paper-out.
    result = wait_for_completion(
        target, doc_name, timeout_seconds=spool_timeout_seconds
    )
    if not result.success:
        raise PrinterError(result.message)
