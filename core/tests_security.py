from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from .file_security import document_upload_validator


class SecureFileValidatorTests(SimpleTestCase):
    def test_rejects_disguised_executable(self):
        uploaded = SimpleUploadedFile("report.pdf", b"MZ executable content")
        with self.assertRaises(ValidationError):
            document_upload_validator(uploaded)

    def test_accepts_pdf_signature(self):
        uploaded = SimpleUploadedFile("report.pdf", b"%PDF-1.7\nexample")
        document_upload_validator(uploaded)

    def test_direct_private_media_url_is_not_served(self):
        self.assertEqual(self.client.get("/media/task_files/report.pdf").status_code, 404)

    def test_security_headers_are_present(self):
        response = self.client.get("/login/")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", response["Content-Security-Policy"])
        self.assertIn("geolocation=()", response["Permissions-Policy"])
