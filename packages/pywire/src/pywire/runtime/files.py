from dataclasses import dataclass
from typing import Any


@dataclass
class FileUpload:
    """A file received with a form submission.

    ``size`` is always counted from the bytes the server received, never
    taken from the client.
    """

    filename: str
    content_type: str
    size: int
    content: bytes

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
        from pydantic_core import core_schema

        # Only the server builds FileUpload objects (from a multipart part or
        # a verified upload id), so validation is an instance check: nothing
        # a client sends as plain data can become a file.
        return core_schema.is_instance_schema(cls)

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema: Any, handler: Any) -> Any:
        return {"type": "string", "format": "binary"}
