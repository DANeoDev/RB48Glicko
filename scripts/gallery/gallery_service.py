"""Gallery service: image metadata extraction, EXIF date parsing, sorting, and upload handling."""

import os
from pathlib import Path
import re
import random
from datetime import datetime
from PIL import Image, ExifTags
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def get_gallery_dir() -> Path:
    """Return the absolute path to the gallery images directory."""
    custom_dir = os.environ.get("RB48_GALLERY_DIR")
    if custom_dir:
        p = Path(custom_dir)
    else:
        p = Path(__file__).resolve().parents[2] / "web" / "static" / "images" / "gallery"
    p.mkdir(parents=True, exist_ok=True)
    return p


def extract_capture_date(image_path: Path) -> datetime:
    """Extract capture date from EXIF tags, filename pattern, or file modification time."""
    # 1. Try EXIF metadata
    try:
        with Image.open(image_path) as img:
            exif = img.getexif()
            if exif:
                exif_ifd = {}
                try:
                    exif_ifd = exif.get_ifd(0x8769)
                except Exception:
                    pass

                candidate_date_str = (
                    exif_ifd.get(36867)
                    or exif_ifd.get(36868)
                    or exif.get(306)
                )
                if candidate_date_str:
                    clean_str = str(candidate_date_str).strip()[:19]
                    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d", "%Y-%m-%d"):
                        try:
                            return datetime.strptime(clean_str, fmt)
                        except ValueError:
                            continue
    except Exception:
        pass

    # 2. Try filename pattern (e.g. 2025-01-08, 20250108, IMG_20250108_...)
    stem = image_path.stem
    match = re.search(r"(\d{4})[-_](\d{2})[-_](\d{2})", stem)
    if match:
        try:
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            if 1990 <= year <= 2050 and 1 <= month <= 12 and 1 <= day <= 31:
                return datetime(year, month, day, 12, 0, 0)
        except Exception:
            pass

    match_dense = re.search(r"(?:IMG_|PXP_|VID_)?(\d{4})(\d{2})(\d{2})", stem)
    if match_dense:
        try:
            year, month, day = int(match_dense.group(1)), int(match_dense.group(2)), int(match_dense.group(3))
            if 1990 <= year <= 2050 and 1 <= month <= 12 and 1 <= day <= 31:
                return datetime(year, month, day, 12, 0, 0)
        except Exception:
            pass

    # 3. Fallback to file creation / modification timestamp
    try:
        stat = image_path.stat()
        ts = min(stat.st_ctime, stat.st_mtime) if stat.st_ctime > 0 else stat.st_mtime
        return datetime.fromtimestamp(ts)
    except Exception:
        return datetime.now()


def get_image_dimensions(image_path: Path):
    """Read image width and height without loading pixels."""
    try:
        with Image.open(image_path) as img:
            return img.width, img.height
    except Exception:
        return None, None


def get_gallery_images(sort_by="random", seed=None):
    """Return list of gallery image dicts sorted according to sort_by."""
    gallery_dir = get_gallery_dir()
    images = []

    for f in gallery_dir.iterdir():
        if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS:
            try:
                stat = f.stat()
                added_date = datetime.fromtimestamp(stat.st_mtime)
                capture_date = extract_capture_date(f)
                width, height = get_image_dimensions(f)
                size_kb = round(stat.st_size / 1024, 1)

                images.append({
                    "filename": f.name,
                    "url": f"/static/images/gallery/{f.name}",
                    "size_kb": size_kb,
                    "width": width,
                    "height": height,
                    "added_date": added_date,
                    "added_date_str": added_date.strftime("%d.%m.%Y"),
                    "capture_date": capture_date,
                    "capture_date_str": capture_date.strftime("%d.%m.%Y"),
                })
            except Exception:
                continue

    if sort_by == "capture_newest":
        images.sort(key=lambda x: x["capture_date"], reverse=True)
    elif sort_by == "capture_oldest":
        images.sort(key=lambda x: x["capture_date"], reverse=False)
    elif sort_by == "added_newest":
        images.sort(key=lambda x: x["added_date"], reverse=True)
    elif sort_by == "added_oldest":
        images.sort(key=lambda x: x["added_date"], reverse=False)
    elif sort_by == "random":
        r = random.Random(seed) if seed is not None else random.Random()
        r.shuffle(images)
    else:
        random.shuffle(images)

    return images


def save_gallery_images(files, username="user"):
    """Validate and save uploaded image files. Returns (saved_count, error_messages)."""
    gallery_dir = get_gallery_dir()
    saved = 0
    errors = []

    for file_storage in files:
        if not file_storage or not file_storage.filename:
            continue

        raw_filename = file_storage.filename
        ext = Path(raw_filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            errors.append(f"Format '{ext}' nicht unterstützt ({raw_filename}).")
            continue

        base_name = Path(raw_filename).stem
        sanitized_base = secure_filename(base_name)
        if not sanitized_base:
            sanitized_base = "upload"

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_name = f"{timestamp}_{sanitized_base}{ext}"
        target_path = gallery_dir / target_name

        counter = 1
        while target_path.exists():
            target_name = f"{timestamp}_{sanitized_base}_{counter}{ext}"
            target_path = gallery_dir / target_name
            counter += 1

        try:
            file_storage.save(str(target_path))
            try:
                with Image.open(target_path) as img:
                    img.verify()
                saved += 1
            except Exception:
                if target_path.exists():
                    target_path.unlink()
                errors.append(f"Ungültige Bilddatei ({raw_filename}).")
        except Exception as e:
            errors.append(f"Fehler beim Speichern von {raw_filename}: {str(e)}")

    return saved, errors
