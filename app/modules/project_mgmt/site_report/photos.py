"""Photo files: resize, thumbnail, EXIF date/GPS, distance from site, storage."""

import hashlib
import io
import math
import os
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageOps, ExifTags

IST = timezone(timedelta(hours=5, minutes=30))

MAX_EDGE = 1600        # stored photo (and what the AI sees)
THUMB_EDGE = 400
JPEG_QUALITY = 82
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIC", "HEIF", "MPO"}


class PhotoError(ValueError):
    pass


def now_ist():
    """Current India time as a naive datetime (how the ERP stores site times)."""
    return datetime.now(IST).replace(tzinfo=None)


def parse_client_time(value):
    """ISO time from the phone/browser → naive India time, or None."""
    if not value:
        return None
    try:
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(IST).replace(tzinfo=None)
    return dt


def _gps_to_deg(values, ref):
    try:
        d, m, s = (float(x) for x in values)
        deg = d + m / 60 + s / 3600
        return -deg if ref in ("S", "W") else deg
    except Exception:
        return None


def read_exif(img):
    """(taken_at, lat, lng) from a photo's EXIF, each None when missing."""
    taken_at = lat = lng = None
    try:
        exif = img.getexif()
        if not exif:
            return None, None, None
        ifd = exif.get_ifd(ExifTags.IFD.Exif) if hasattr(ExifTags, "IFD") else {}
        raw = ifd.get(36867) or ifd.get(36868) or exif.get(306)  # DateTimeOriginal / Digitized / DateTime
        if raw:
            try:
                taken_at = datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S")
            except ValueError:
                taken_at = None
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo) if hasattr(ExifTags, "IFD") else {}
        if gps and 2 in gps and 4 in gps:
            lat = _gps_to_deg(gps[2], gps.get(1, "N"))
            lng = _gps_to_deg(gps[4], gps.get(3, "E"))
    except Exception:
        pass
    return taken_at, lat, lng


def distance_m(lat1, lng1, lat2, lng2):
    """Great-circle distance in metres."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def prepare(data: bytes):
    """Validate and shrink an upload.

    Returns dict: jpeg (bytes), thumb (bytes), width, height, sha256,
    exif_taken_at, exif_lat, exif_lng.
    """
    if not data:
        raise PhotoError("Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise PhotoError("Photo is larger than 25 MB")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise PhotoError("Not a photo (or a format the server can't read)")
    if (img.format or "").upper() not in ALLOWED_FORMATS:
        raise PhotoError(f"Unsupported photo type: {img.format}")

    exif_taken_at, exif_lat, exif_lng = read_exif(img)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    full = img.copy()
    full.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
    out = io.BytesIO()
    full.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)

    thumb = img.copy()
    thumb.thumbnail((THUMB_EDGE, THUMB_EDGE), Image.LANCZOS)
    tout = io.BytesIO()
    thumb.save(tout, "JPEG", quality=75, optimize=True)

    return {
        "jpeg": out.getvalue(),
        "thumb": tout.getvalue(),
        "width": full.width,
        "height": full.height,
        "sha256": hashlib.sha256(data).hexdigest(),
        "exif_taken_at": exif_taken_at,
        "exif_lat": exif_lat,
        "exif_lng": exif_lng,
    }


def store(project_code, report_date, name, jpeg: bytes, thumb: bytes):
    """Save under MEDIA_BASE_PATH/site_photos/<project>/<date>/ → (file_url, thumb_url)."""
    base_path = os.getenv("MEDIA_BASE_PATH")
    base_url = os.getenv("MEDIA_BASE_URL")
    if not base_path or not base_url:
        raise PhotoError("MEDIA_BASE_PATH or MEDIA_BASE_URL not set on the server")
    safe_project = "".join(c for c in str(project_code) if c.isalnum() or c in "-_") or "project"
    rel = f"site_photos/{safe_project}/{report_date.isoformat()}"
    folder = os.path.join(base_path, rel)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, f"{name}.jpg"), "wb") as f:
        f.write(jpeg)
    with open(os.path.join(folder, f"{name}_t.jpg"), "wb") as f:
        f.write(thumb)
    return f"{base_url}/{rel}/{name}.jpg", f"{base_url}/{rel}/{name}_t.jpg"


def read_stored(file_url):
    """Bytes of a stored photo (for the AI), or None."""
    from app.cloudinary_uploader import local_path_from_url

    path = local_path_from_url(file_url)
    if not path or not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def remove_stored(*urls):
    from app.cloudinary_uploader import delete_file_from_storage

    for u in urls:
        if u:
            delete_file_from_storage(u)
