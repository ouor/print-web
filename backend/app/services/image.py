from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from app.core.config import settings

# Register the HEIF opener once at import time so Image.open() can decode
# iPhone uploads (which default to .heic).
register_heif_opener()

ALLOWED_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "WEBP", "HEIF", "HEIC"})
THUMB_MAX_EDGE = 400


class InvalidImageError(ValueError):
    """Raised when the uploaded bytes are not a usable image."""


def _ensure_upload_dir() -> Path:
    upload_dir = settings.upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def save_image(raw: bytes, job_id: str) -> tuple[Path, Path]:
    """Validate, EXIF-rotate, and persist an uploaded image plus a thumbnail.

    Returns (image_path, thumb_path) relative to the upload directory.
    """
    try:
        with Image.open(BytesIO(raw)) as im:
            im.load()
            if im.format not in ALLOWED_FORMATS:
                raise InvalidImageError(f"unsupported image format: {im.format}")
            rotated = ImageOps.exif_transpose(im)
            if rotated.mode not in ("RGB", "RGBA"):
                rotated = rotated.convert("RGB")
    except UnidentifiedImageError as e:
        raise InvalidImageError("file is not a recognizable image") from e

    upload_dir = _ensure_upload_dir()
    image_path = upload_dir / f"{job_id}.jpg"
    thumb_path = upload_dir / f"{job_id}_thumb.jpg"

    # Normalize to JPEG for consistency and smaller disk footprint.
    save_target = rotated.convert("RGB") if rotated.mode == "RGBA" else rotated
    save_target.save(image_path, format="JPEG", quality=92, optimize=True)

    thumb = save_target.copy()
    thumb.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE))
    thumb.save(thumb_path, format="JPEG", quality=85, optimize=True)

    return image_path, thumb_path


def delete_image_files(*paths: str | None) -> None:
    for p in paths:
        if not p:
            continue
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            # Best-effort cleanup; the retention sweep will retry next run.
            pass
