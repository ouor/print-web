"""Windows GDI printing via pywin32.

Renders a single image to one page, scaled to fit the printable area with
aspect ratio preserved. Works against any installed Windows printer.
"""
from __future__ import annotations

import sys
from pathlib import Path

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


class PrinterError(RuntimeError):
    pass


def resolve_printer_name(configured: str | None) -> str:
    if sys.platform != "win32":
        raise PrinterError("printing is only supported on Windows")
    if configured:
        return configured
    return win32print.GetDefaultPrinter()


def print_image(image_path: str | Path, printer_name: str | None = None) -> None:
    """Send one image to the printer as a single page.

    Raises PrinterError on failure.
    """
    if sys.platform != "win32":
        raise PrinterError("printing is only supported on Windows")

    target = resolve_printer_name(printer_name)
    path = Path(image_path)
    if not path.exists():
        raise PrinterError(f"image not found: {path}")

    hdc = win32ui.CreateDC()
    try:
        hdc.CreatePrinterDC(target)
    except Exception as e:  # pragma: no cover - depends on installed drivers
        raise PrinterError(f"could not open printer '{target}': {e}") from e

    try:
        page_w = hdc.GetDeviceCaps(_PHYSICALWIDTH)
        page_h = hdc.GetDeviceCaps(_PHYSICALHEIGHT)
        offset_x = hdc.GetDeviceCaps(_PHYSICALOFFSETX)
        offset_y = hdc.GetDeviceCaps(_PHYSICALOFFSETY)
        printable_w = hdc.GetDeviceCaps(_HORZRES)
        printable_h = hdc.GetDeviceCaps(_VERTRES)

        with Image.open(path) as im:
            im.load()
            img_w, img_h = im.size
            scale = min(printable_w / img_w, printable_h / img_h)
            draw_w = int(img_w * scale)
            draw_h = int(img_h * scale)
            x = (page_w - draw_w) // 2 - offset_x
            y = (page_h - draw_h) // 2 - offset_y

            hdc.StartDoc(f"print-web: {path.name}")
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
