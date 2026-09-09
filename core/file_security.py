from pathlib import Path

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible


@deconstructible
class SecureFileValidator:
    """Validate size, extension, and common file signatures before storage."""

    def __init__(self, allowed_extensions, max_size=10 * 1024 * 1024):
        self.allowed_extensions = tuple(sorted(ext.lower() for ext in allowed_extensions))
        self.max_size = max_size

    def __call__(self, uploaded_file):
        extension = Path(uploaded_file.name).suffix.lower()
        if extension not in self.allowed_extensions:
            raise ValidationError(
                "Unsupported file type. Allowed types: %(types)s.",
                params={"types": ", ".join(self.allowed_extensions)},
            )
        if uploaded_file.size > self.max_size:
            raise ValidationError("File size must not exceed 10 MB.")

        position = uploaded_file.tell()
        header = uploaded_file.read(12)
        uploaded_file.seek(position)
        signatures = {
            ".pdf": (b"%PDF-",),
            ".docx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
            ".xlsx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
            ".pptx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
            ".zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
            ".doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
            ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
            ".ppt": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
            ".png": (b"\x89PNG\r\n\x1a\n",),
            ".jpg": (b"\xff\xd8\xff",),
            ".jpeg": (b"\xff\xd8\xff",),
        }
        expected = signatures.get(extension)
        if expected and not any(header.startswith(signature) for signature in expected):
            raise ValidationError("The file content does not match its filename extension.")


document_upload_validator = SecureFileValidator(
    {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".jpg", ".jpeg", ".png", ".zip"}
)
pdf_upload_validator = SecureFileValidator({".pdf"})
