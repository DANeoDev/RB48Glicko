"""Gallery routes: viewing gallery, sorting images, and uploading new photos."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from scripts.gallery.gallery_service import (
    delete_gallery_image,
    get_gallery_images,
    save_gallery_images,
)
from web.services.security import Tier, get_current_user, require_tier, require_webmaster
from web.services.translations import t

gallery_bp = Blueprint("gallery", __name__)


@gallery_bp.route("/gallery")
@require_tier(Tier.USER)
def gallery():
    """Render community gallery page with selected sorting."""
    sort_mode = request.args.get("sort", "random").lower()
    valid_sorts = {"random", "capture_newest", "capture_oldest", "added_newest", "added_oldest"}
    if sort_mode not in valid_sorts:
        sort_mode = "random"

    seed_raw = request.args.get("seed")
    seed = int(seed_raw) if seed_raw and seed_raw.isdigit() else None

    images = get_gallery_images(sort_by=sort_mode, seed=seed)
    return render_template(
        "gallery.html",
        images=images,
        current_sort=sort_mode,
        seed=seed,
    )


@gallery_bp.route("/gallery/upload", methods=["POST"])
@require_tier(Tier.USER)
def upload():
    """Upload one or multiple photos to the gallery."""
    user = get_current_user()
    username = user["username"] if user else "user"

    files = request.files.getlist("images")
    if not files or (len(files) == 1 and not files[0].filename):
        single_file = request.files.get("image")
        files = [single_file] if single_file and single_file.filename else []

    if not files:
        flash(t("gallery.no_files_selected", "Keine Dateien zum Hochladen ausgewählt."), "warning")
        return redirect(url_for("gallery.gallery"))

    saved_count, errors = save_gallery_images(files, username=username)

    if saved_count > 0:
        if saved_count == 1:
            flash(t("gallery.upload_success_single", "1 Foto erfolgreich zur Galerie hinzugefügt!"), "success")
        else:
            flash(t("gallery.upload_success_multi", "{count} Fotos erfolgreich zur Galerie hinzugefügt!", count=saved_count), "success")

    for err in errors:
        flash(err, "warning")

    return redirect(url_for("gallery.gallery", sort="added_newest"))


@gallery_bp.route("/gallery/delete", methods=["POST"])
@require_webmaster
def delete_image():
    """Delete a photo from the gallery (Webmaster only)."""
    filename = request.form.get("filename", "").strip()
    sort_mode = request.form.get("sort", "random")

    if not filename:
        flash(t("gallery.delete_missing_filename", "Kein Dateiname angegeben."), "danger")
        return redirect(url_for("gallery.gallery", sort=sort_mode))

    success = delete_gallery_image(filename)
    if success:
        flash(t("gallery.delete_success", "Foto '{filename}' wurde erfolgreich gelöscht.", filename=filename), "success")
    else:
        flash(t("gallery.delete_error", "Foto konnte nicht gelöscht werden oder wurde nicht gefunden."), "warning")

    return redirect(url_for("gallery.gallery", sort=sort_mode))
