import json
import tempfile
import time
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

    def __init__(
        self,
        max_upload_size: int = 10 * 1024 * 1024,
        storage_dir: Optional[Path] = None,
    ) -> None:
        default_dir = Path(tempfile.gettempdir()) / "pywire_uploads"
        self._temp_dir = (storage_dir or default_dir).resolve()
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._max_upload_size = max_upload_size
        self._cleanup_interval_seconds = 30.0
        self._last_cleanup_ts = 0.0

    @property
    def storage_dir(self) -> Path:
        return self._temp_dir

    def configure_storage(self, storage_dir: Path) -> None:
        self._temp_dir = storage_dir.resolve()
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    @property
    def max_upload_size(self) -> int:
        return self._max_upload_size

    @max_upload_size.setter
    def max_upload_size(self, value: int) -> None:
        self._max_upload_size = max(1, int(value))

    def save(self, file: UploadFile, max_size: Optional[int] = None) -> str:
        """
        Save an uploaded file and return a unique ID.
        """
        self._cleanup_if_due()

        upload_id = str(uuid.uuid4())
        file_path = self._temp_dir / upload_id
        limit = self._max_upload_size if max_size is None else max(1, int(max_size))
        written = 0

        with open(file_path, "wb") as f:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    f.close()
                    file_path.unlink(missing_ok=True)
                    raise ValueError("Payload Too Large")
                f.write(chunk)

        meta_path = file_path.with_suffix(".meta")
        metadata = {
            "filename": file.filename or "unknown",
            "content_type": file.content_type or "application/octet-stream",
            "size": written,
            "created_at": time.time(),
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f)

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
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                filename = meta.get("filename", "unknown")
                content_type = meta.get("content_type", "application/octet-stream")
                size = int(meta.get("size", file_path.stat().st_size))

            return FileUpload(
                filename=filename,
                content_type=content_type,
                size=size,
                content=file_path.read_bytes(),
            )
        except (OSError, ValueError, json.JSONDecodeError) as e:
            print(f"Error retrieving upload {upload_id}: {e}")
            return None

    def delete(self, upload_id: str) -> None:
        file_path = self._temp_dir / upload_id
        meta_path = file_path.with_suffix(".meta")
        file_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)

    def cleanup(self, max_age_seconds: int = 300) -> int:
        cutoff = time.time() - max_age_seconds
        removed = 0
        for meta_path in self._temp_dir.glob("*.meta"):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                created_at = float(meta.get("created_at", 0))
            except (OSError, ValueError, json.JSONDecodeError):
                created_at = 0.0

            if created_at >= cutoff:
                continue

            file_path = meta_path.with_suffix("")
            file_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            removed += 1
        return removed

    def _cleanup_if_due(self) -> None:
        now = time.time()
        if (now - self._last_cleanup_ts) < self._cleanup_interval_seconds:
            return
        self.cleanup()
        self._last_cleanup_ts = now


# Global instance
upload_manager = UploadManager()
