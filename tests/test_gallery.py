import io
import os
from pathlib import Path
import tempfile
import time
import unittest
from datetime import datetime
from PIL import Image

from scripts.accounts.auth import register_user, get_user
from scripts.accounts.database import (
    get_accounts_connection,
    mark_email_verified,
    approve_user,
    get_gallery_photo_metadata,
)
from scripts.gallery.gallery_service import (
    get_gallery_images,
    extract_capture_date,
    save_gallery_images,
    update_gallery_image_date,
)
from web.app import create_app


class GalleryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_accounts_db = Path(self.temp_dir.name) / "test_accounts.db"
        self.test_gallery_dir = Path(self.temp_dir.name) / "gallery"
        self.test_gallery_dir.mkdir(parents=True, exist_ok=True)

        os.environ["RB48_ACCOUNTS_DATABASE_FILE"] = str(self.test_accounts_db)
        os.environ["RB48_GALLERY_DIR"] = str(self.test_gallery_dir)

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        os.environ.pop("RB48_ACCOUNTS_DATABASE_FILE", None)
        os.environ.pop("RB48_GALLERY_DIR", None)
        self.temp_dir.cleanup()

    def create_user(self, role="user", verified=True, approved=True):
        unique_name = f"gal_usr_{int(time.time() * 1000000)}"
        email = f"{unique_name}@example.com"
        user_id, _ = register_user(unique_name, email, "password123", role=role)

        conn = get_accounts_connection()
        try:
            if verified:
                mark_email_verified(conn, user_id)
            if approved or role in ("admin", "webmaster"):
                approve_user(conn, user_id, approved=True)
        finally:
            conn.close()

        return get_user(user_id)

    def create_dummy_image(self, filename, width=100, height=100, color=(255, 0, 0), exif_date=None):
        img_path = self.test_gallery_dir / filename
        img = Image.new("RGB", (width, height), color=color)
        if exif_date:
            exif = img.getexif()
            exif[306] = exif_date
            img.save(str(img_path), "JPEG", exif=exif)
        else:
            img.save(str(img_path))
        return img_path

    def test_gallery_access_control(self):
        # 1. Anonymous visitor is redirected to login
        resp = self.client.get("/gallery")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

        # 2. Registered and approved user can access
        user = self.create_user(role="user", verified=True, approved=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        resp2 = self.client.get("/gallery")
        self.assertEqual(resp2.status_code, 200)
        html = resp2.data.decode("utf-8")
        self.assertIn("Galerie", html)
        self.assertIn("Fotos hinzufügen", html)

    def test_metadata_extraction_and_sorting(self):
        # Create images with different capture dates
        p1 = self.create_dummy_image("2024-06-15.jpg", color=(100, 0, 0))
        p2 = self.create_dummy_image("IMG_20220101_100000.jpg", color=(0, 100, 0))
        p3 = self.create_dummy_image("exif_pic.jpg", color=(0, 0, 100), exif_date="2023:09:20 14:30:00")

        d1 = extract_capture_date(p1)
        self.assertEqual((d1.year, d1.month, d1.day), (2024, 6, 15))

        d2 = extract_capture_date(p2)
        self.assertEqual((d2.year, d2.month, d2.day), (2022, 1, 1))

        d3 = extract_capture_date(p3)
        self.assertEqual((d3.year, d3.month, d3.day), (2023, 9, 20))

        # Sort: capture_newest -> 2024-06-15, then 2023-09-20, then 2022-01-01
        newest = get_gallery_images(sort_by="capture_newest")
        self.assertEqual(len(newest), 3)
        self.assertEqual(newest[0]["filename"], "2024-06-15.jpg")
        self.assertEqual(newest[1]["filename"], "exif_pic.jpg")
        self.assertEqual(newest[2]["filename"], "IMG_20220101_100000.jpg")

        # Sort: capture_oldest -> reverse
        oldest = get_gallery_images(sort_by="capture_oldest")
        self.assertEqual(oldest[0]["filename"], "IMG_20220101_100000.jpg")
        self.assertEqual(oldest[2]["filename"], "2024-06-15.jpg")

        # Sort: random -> returns all 3
        rnd = get_gallery_images(sort_by="random", seed=42)
        self.assertEqual(len(rnd), 3)

    def test_upload_route_records_uploader(self):
        user = self.create_user(role="user", verified=True, approved=True)
        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        # 1. Upload valid image
        img_buffer = io.BytesIO()
        test_img = Image.new("RGB", (80, 80), color="blue")
        test_img.save(img_buffer, "PNG")
        img_buffer.seek(0)

        data = {
            "images": [(img_buffer, "matchday_test.png")]
        }
        resp = self.client.post("/gallery/upload", data=data, content_type="multipart/form-data", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        images = get_gallery_images(viewer_user_id=user["id"], is_webmaster=False)
        self.assertEqual(len(images), 1)
        saved_filename = images[0]["filename"]
        self.assertIn("matchday_test", saved_filename)
        self.assertEqual(images[0]["uploader_user_id"], user["id"])
        self.assertEqual(images[0]["uploader_username"], user["username"])
        self.assertTrue(images[0]["can_manage"])

        # Check DB directly
        conn = get_accounts_connection()
        try:
            meta = get_gallery_photo_metadata(conn, saved_filename)
            self.assertIsNotNone(meta)
            self.assertEqual(meta["uploader_user_id"], user["id"])
            self.assertEqual(meta["uploader_username"], user["username"])
        finally:
            conn.close()

        # Another user viewing the image
        other_user = self.create_user(role="user", verified=True, approved=True)
        images_other = get_gallery_images(viewer_user_id=other_user["id"], is_webmaster=False)
        self.assertEqual(len(images_other), 1)
        self.assertFalse(images_other[0]["can_manage"])

        # Webmaster viewing the image
        images_wm = get_gallery_images(viewer_user_id=other_user["id"], is_webmaster=True)
        self.assertTrue(images_wm[0]["can_manage"])

    def test_uploader_can_delete_own_image(self):
        user1 = self.create_user(role="user", verified=True, approved=True)
        user2 = self.create_user(role="user", verified=True, approved=True)

        # Upload image as user1
        with self.client.session_transaction() as sess:
            sess["user_id"] = user1["id"]

        img_buf = io.BytesIO()
        Image.new("RGB", (50, 50), color="green").save(img_buf, "JPEG")
        img_buf.seek(0)
        self.client.post("/gallery/upload", data={"images": [(img_buf, "user1_pic.jpg")]}, content_type="multipart/form-data", follow_redirects=True)

        images = get_gallery_images()
        self.assertEqual(len(images), 1)
        filename = images[0]["filename"]
        img_path = self.test_gallery_dir / filename
        self.assertTrue(img_path.exists())

        # user2 attempts to delete user1's photo -> fails
        with self.client.session_transaction() as sess:
            sess["user_id"] = user2["id"]
        resp2 = self.client.post("/gallery/delete", data={"filename": filename}, follow_redirects=True)
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(img_path.exists())

        # user1 deletes their own photo -> succeeds
        with self.client.session_transaction() as sess:
            sess["user_id"] = user1["id"]
        resp1 = self.client.post("/gallery/delete", data={"filename": filename}, follow_redirects=True)
        self.assertEqual(resp1.status_code, 200)
        self.assertFalse(img_path.exists())

        conn = get_accounts_connection()
        try:
            self.assertIsNone(get_gallery_photo_metadata(conn, filename))
        finally:
            conn.close()

    def test_webmaster_can_delete_any_image(self):
        user = self.create_user(role="user", verified=True, approved=True)
        wm = self.create_user(role="webmaster")

        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]

        img_buf = io.BytesIO()
        Image.new("RGB", (50, 50), color="purple").save(img_buf, "JPEG")
        img_buf.seek(0)
        self.client.post("/gallery/upload", data={"images": [(img_buf, "user_photo.jpg")]}, content_type="multipart/form-data", follow_redirects=True)

        images = get_gallery_images()
        filename = images[0]["filename"]
        img_path = self.test_gallery_dir / filename

        # Webmaster deletes user's image
        with self.client.session_transaction() as sess:
            sess["user_id"] = wm["id"]
        resp_wm = self.client.post("/gallery/delete", data={"filename": filename}, follow_redirects=True)
        self.assertEqual(resp_wm.status_code, 200)
        self.assertFalse(img_path.exists())

    def test_update_capture_date(self):
        user1 = self.create_user(role="user", verified=True, approved=True)
        user2 = self.create_user(role="user", verified=True, approved=True)
        wm = self.create_user(role="webmaster")

        with self.client.session_transaction() as sess:
            sess["user_id"] = user1["id"]

        img_buf = io.BytesIO()
        Image.new("RGB", (50, 50), color="orange").save(img_buf, "JPEG")
        img_buf.seek(0)
        self.client.post("/gallery/upload", data={"images": [(img_buf, "event_photo.jpg")]}, content_type="multipart/form-data", follow_redirects=True)

        images = get_gallery_images()
        filename = images[0]["filename"]

        # 1. user2 tries to edit date of user1's photo -> forbidden / rejected
        with self.client.session_transaction() as sess:
            sess["user_id"] = user2["id"]
        resp = self.client.post("/gallery/update-date", data={"filename": filename, "capture_date": "2021-05-10"}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        images = get_gallery_images()
        self.assertNotEqual(images[0]["capture_date_iso"], "2021-05-10")

        # 2. user1 updates their own photo's capture date -> succeeds
        with self.client.session_transaction() as sess:
            sess["user_id"] = user1["id"]
        resp_ok = self.client.post("/gallery/update-date", data={"filename": filename, "capture_date": "2021-05-10"}, follow_redirects=True)
        self.assertEqual(resp_ok.status_code, 200)
        images = get_gallery_images()
        self.assertEqual(images[0]["capture_date_iso"], "2021-05-10")
        self.assertEqual(images[0]["capture_date_str"], "10.05.2021")

        # 3. Webmaster updates capture date to 2019-12-25 -> succeeds
        with self.client.session_transaction() as sess:
            sess["user_id"] = wm["id"]
        resp_wm = self.client.post("/gallery/update-date", data={"filename": filename, "capture_date": "2019-12-25"}, follow_redirects=True)
        self.assertEqual(resp_wm.status_code, 200)
        images = get_gallery_images()
        self.assertEqual(images[0]["capture_date_iso"], "2019-12-25")
        self.assertEqual(images[0]["capture_date_str"], "25.12.2019")

        # 4. Invalid date string handled gracefully
        resp_bad = self.client.post("/gallery/update-date", data={"filename": filename, "capture_date": "invalid-date"}, follow_redirects=True)
        self.assertEqual(resp_bad.status_code, 200)
        # Date remains 2019-12-25
        images = get_gallery_images()
        self.assertEqual(images[0]["capture_date_iso"], "2019-12-25")


if __name__ == "__main__":
    unittest.main()
