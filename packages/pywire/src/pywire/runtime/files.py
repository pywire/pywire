from dataclasses import dataclass


@dataclass
class FileUpload:
    """Represents an uploaded file."""

    filename: str
    content_type: str
    size: int
    content: bytes

    @classmethod
    def from_dict(cls, data: dict) -> "FileUpload":
        """Create from dictionary (e.g. from JSON payload)."""
        import base64

        # content might be base64 encoded string from client
        content_data = data.get("content", b"")
        if isinstance(content_data, str):
            # assume base64 if it's a string, or raw content?
            # Client usually sends data URL: "data:image/png;base64,....."
            if content_data.startswith("data:"):
                header, encoded = content_data.split(",", 1)
                content_bytes = base64.b64decode(encoded)
            else:
                # Fallback or raw base64
                try:
                    content_bytes = base64.b64decode(content_data)
                except Exception:
                    content_bytes = content_data.encode("utf-8")
        else:
            content_bytes = content_data

        return cls(
            filename=data.get("name", "unknown"),
            content_type=data.get("type", "application/octet-stream"),
            size=data.get("size", 0),
            content=content_bytes,
        )
