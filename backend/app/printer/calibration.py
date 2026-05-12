"""Calibrate the printer for edge-to-edge ("borderless") printing via the
oversized-paper trick.

The driver enforces a mechanical unprintable margin around any sheet
(say, ~5.6mm on the HP Inkjet 3000 at 4x6). To get a 4x6 sheet to fill
edge-to-edge, we tell the driver the page is bigger than reality by
exactly those margins. The driver's printable area then equals the real
paper, so anything we draw to fill the printable area lands on the
paper edge-to-edge.

Done once at server start via SetPrinter level 9 (per-user, no admin);
restored at shutdown so other apps aren't surprised by the override.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

if sys.platform == "win32":
    import win32print
    import win32ui

log = logging.getLogger(__name__)

# DEVMODE field flag bits
_DM_ORIENTATION = 0x0001
_DM_PAPERSIZE = 0x0002
_DM_PAPERLENGTH = 0x0004
_DM_PAPERWIDTH = 0x0008
_DM_PRINTQUALITY = 0x0400
_DM_COLOR = 0x0800
_DM_MEDIATYPE = 0x1000

_DMORIENT_PORTRAIT = 1
_DMORIENT_LANDSCAPE = 2
_DMCOLOR_COLOR = 2
_DMRES_HIGH = -4  # driver's highest quality mode

# Photo print defaults pushed at calibration time. 263 is the Brother
# driver's "기타 사진 용지" (generic glossy photo paper); on a different
# printer, run win32print.DeviceCapabilities(name, "", 34/35) to find the
# right code for the loaded media.
_PHOTO_PRINT_QUALITY = _DMRES_HIGH
_PHOTO_MEDIA_TYPE = 263

# GDI DeviceCaps indices
_HORZRES, _VERTRES = 8, 10
_PHYSICALWIDTH, _PHYSICALHEIGHT = 110, 111
_PHYSICALOFFSETX, _PHYSICALOFFSETY = 112, 113
_LOGPIXELSX = 88


@dataclass(frozen=True)
class PrintGeometry:
    """GDI-reported canvas for the active printer, in driver pixels."""
    physical_w_px: int
    physical_h_px: int
    content_w_px: int   # printable region — equals the real paper after the oversize trick
    content_h_px: int
    content_offset_x: int
    content_offset_y: int
    dpi: int


@dataclass(frozen=True)
class DevModeSnapshot:
    """Per-user DEVMODE values captured before we modified them."""
    paper_size: int
    paper_width: int    # 0.1 mm
    paper_length: int   # 0.1 mm
    orientation: int
    color: int
    print_quality: int
    media_type: int
    fields: int


class CalibrationError(RuntimeError):
    pass


def _probe(printer_name: str) -> PrintGeometry:
    hdc = win32ui.CreateDC()
    hdc.CreatePrinterDC(printer_name)
    try:
        return PrintGeometry(
            physical_w_px=hdc.GetDeviceCaps(_PHYSICALWIDTH),
            physical_h_px=hdc.GetDeviceCaps(_PHYSICALHEIGHT),
            content_w_px=hdc.GetDeviceCaps(_HORZRES),
            content_h_px=hdc.GetDeviceCaps(_VERTRES),
            content_offset_x=hdc.GetDeviceCaps(_PHYSICALOFFSETX),
            content_offset_y=hdc.GetDeviceCaps(_PHYSICALOFFSETY),
            dpi=hdc.GetDeviceCaps(_LOGPIXELSX),
        )
    finally:
        hdc.DeleteDC()


def _level9_info_with_devmode(h):
    """Read PRINTER_INFO_9. If pDevMode is None (no per-user override yet)
    seed it with the global default (level 2) so callers can mutate."""
    info = win32print.GetPrinter(h, 9)
    if info["pDevMode"] is None:
        info2 = win32print.GetPrinter(h, 2)
        info["pDevMode"] = info2["pDevMode"]
    if info["pDevMode"] is None:
        raise CalibrationError("no DEVMODE available")
    return info


def _snapshot(printer_name: str) -> DevModeSnapshot:
    h = win32print.OpenPrinter(printer_name)
    try:
        info = _level9_info_with_devmode(h)
        dm = info["pDevMode"]
        return DevModeSnapshot(
            paper_size=dm.PaperSize,
            paper_width=dm.PaperWidth,
            paper_length=dm.PaperLength,
            orientation=dm.Orientation,
            color=dm.Color,
            print_quality=dm.PrintQuality,
            media_type=dm.MediaType,
            fields=dm.Fields,
        )
    finally:
        win32print.ClosePrinter(h)


def _push_custom_paper(
    printer_name: str,
    *,
    width_01mm: int,
    length_01mm: int,
    landscape: bool = True,
    color: bool = True,
    print_quality: int = _PHOTO_PRINT_QUALITY,
    media_type: int = _PHOTO_MEDIA_TYPE,
) -> None:
    """Apply a custom paper size to the printer's per-user DEVMODE (level 9
    — no admin needed)."""
    h = win32print.OpenPrinter(printer_name)
    try:
        info = _level9_info_with_devmode(h)
        dm = info["pDevMode"]
        dm.PaperSize = 0  # 0 = use width/length
        dm.PaperWidth = width_01mm
        dm.PaperLength = length_01mm
        dm.Orientation = _DMORIENT_LANDSCAPE if landscape else _DMORIENT_PORTRAIT
        dm.Color = _DMCOLOR_COLOR if color else 1
        dm.PrintQuality = print_quality
        dm.MediaType = media_type
        dm.Fields |= (
            _DM_ORIENTATION | _DM_PAPERSIZE | _DM_PAPERLENGTH | _DM_PAPERWIDTH
            | _DM_COLOR | _DM_PRINTQUALITY | _DM_MEDIATYPE
        )
        info["pDevMode"] = dm
        win32print.SetPrinter(h, 9, info, 0)
    finally:
        win32print.ClosePrinter(h)


def restore_devmode(printer_name: str, snap: DevModeSnapshot) -> None:
    h = win32print.OpenPrinter(printer_name)
    try:
        info = _level9_info_with_devmode(h)
        dm = info["pDevMode"]
        dm.PaperSize = snap.paper_size
        dm.PaperWidth = snap.paper_width
        dm.PaperLength = snap.paper_length
        dm.Orientation = snap.orientation
        dm.Color = snap.color
        dm.PrintQuality = snap.print_quality
        dm.MediaType = snap.media_type
        dm.Fields = snap.fields
        info["pDevMode"] = dm
        win32print.SetPrinter(h, 9, info, 0)
    finally:
        win32print.ClosePrinter(h)


def configure_borderless(
    printer_name: str,
    target_long_mm: float,
    target_short_mm: float,
) -> tuple[PrintGeometry, DevModeSnapshot]:
    """Push an oversized paper size so the driver's printable area equals
    the target (real paper) size. Returns the resulting geometry plus a
    pre-modification snapshot for shutdown restoration.

    target_long_mm:  the longer edge of the actual photo paper, in mm
                     (152.4 = 6 inches for 4x6)
    target_short_mm: the shorter edge (101.6 = 4 inches for 4x6)
    """
    if sys.platform != "win32":
        raise CalibrationError("calibration is only supported on Windows")

    original = _snapshot(printer_name)

    # 1) Probe at the real paper size to learn the driver's margins.
    _push_custom_paper(
        printer_name,
        width_01mm=int(round(target_short_mm * 10)),
        length_01mm=int(round(target_long_mm * 10)),
    )
    base = _probe(printer_name)
    margin_left_mm = base.content_offset_x * 25.4 / base.dpi
    margin_top_mm = base.content_offset_y * 25.4 / base.dpi
    right_px = base.physical_w_px - base.content_offset_x - base.content_w_px
    bottom_px = base.physical_h_px - base.content_offset_y - base.content_h_px
    margin_right_mm = right_px * 25.4 / base.dpi
    margin_bottom_mm = bottom_px * 25.4 / base.dpi

    log.info(
        "%s base @ %.1fx%.1f mm: physical %dx%d px, printable %dx%d px, "
        "margins L/T/R/B = %.2f/%.2f/%.2f/%.2f mm",
        printer_name, target_long_mm, target_short_mm,
        base.physical_w_px, base.physical_h_px,
        base.content_w_px, base.content_h_px,
        margin_left_mm, margin_top_mm, margin_right_mm, margin_bottom_mm,
    )

    # 2) If the driver is already borderless (SELPHY-style), keep the base.
    if (
        base.content_offset_x == 0
        and base.content_offset_y == 0
        and right_px == 0
        and bottom_px == 0
    ):
        log.info("%s reports zero margins; using base config as-is", printer_name)
        return base, original

    # 3) Otherwise expand the paper by the measured margin on each side so
    #    the printable region collapses to (target_long × target_short).
    oversize_long_mm = target_long_mm + margin_left_mm + margin_right_mm
    oversize_short_mm = target_short_mm + margin_top_mm + margin_bottom_mm
    _push_custom_paper(
        printer_name,
        width_01mm=int(round(oversize_short_mm * 10)),
        length_01mm=int(round(oversize_long_mm * 10)),
    )
    final = _probe(printer_name)
    final_content_w_mm = final.content_w_px * 25.4 / final.dpi
    final_content_h_mm = final.content_h_px * 25.4 / final.dpi
    log.info(
        "%s borderless @ %.1fx%.1f mm: physical %dx%d px, printable %dx%d px "
        "(= %.1fx%.1f mm)",
        printer_name, oversize_long_mm, oversize_short_mm,
        final.physical_w_px, final.physical_h_px,
        final.content_w_px, final.content_h_px,
        final_content_w_mm, final_content_h_mm,
    )
    return final, original
