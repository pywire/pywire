import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from starlette.datastructures import UploadFile

from pywire.runtime.files import FileUpload


class UploadManager:
    """
    Manages temporary storage of uploaded files using generated IDs.
    Files are stored in a temporary directory and accessed by ID.
    Ideally, these should be cleaned up after request processing or via a TTL mechanism.
    For this implementation, we rely on OS temp cleaning or process restart for now.
    """

    def __init__(self) -> None:
        self._temp_dir = Path(tempfile.mkdtemp(prefix="pywire_uploads_"))

    def save(self, file: UploadFile) -> str:
        """
        Save an uploaded file and return a unique ID.
        """
        upload_id = str(uuid.uuid4())
        file_path = self._temp_dir / upload_id

        # Save content
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Store metadata in a separate file or just keep it simple?
        # We need filename, content_type, size.
        # Let's write a metadata file next to it.
        # Format: filename\ncontent_type
        # Size comes from file size.

        meta_path = file_path.with_suffix(".meta")
        with open(meta_path, "w") as f:
            f.write(f"{file.filename}\n{file.content_type}")

        return upload_id

    def get(self, upload_id: str) -> Optional[FileUpload]:
        """
        Retrieve a file by ID.
        """
        file_path = self._temp_dir / upload_id
        meta_path = file_path.with_suffix(".meta")

        if not file_path.exists() or not meta_path.exists():
            return None

        try:
            with open(meta_path, "r") as f:
                lines = f.read().splitlines()
                filename = lines[0]
                content_type = lines[1] if len(lines) > 1 else "application/octet-stream"

            return FileUpload(
                filename=filename,
                content_type=content_type,
                size=file_path.stat().st_size,
                content=file_path.read_bytes(),
            )
        except Exception as e:
            print(f"Error retrieving upload {upload_id}: {e}")
            return None


# Global instance
upload_manager = UploadManager()
