"""``UploadField``: size, type and count rules for file fields.

    class Profile(BaseModel):
        avatar: Annotated[Upload, UploadField(max_size="2 MB", accept="image/*")]
        papers: Annotated[list[Upload], UploadField(max_files=3, accept=".pdf")]

The rules render as ``accept=`` and size and count hints the client checks
before it uploads anything, and the server checks them again on submit.
``accept`` compares the name and the type the browser declared, as the
browser does; to trust the bytes, inspect them in the handler.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence, Tuple, Union

from pydantic_core import PydanticCustomError, core_schema

from pywire.runtime.uploads import Upload, format_size, parse_size


@dataclass(frozen=True, init=False)
class UploadField:
    """Rules for an ``Upload`` or ``list[Upload]`` field (use in ``Annotated``)."""

    max_size: Optional[int]
    accept: Tuple[str, ...]
    max_files: Optional[int]

    def __init__(
        self,
        *,
        max_size: Union[int, str, None] = None,
        accept: Union[str, Sequence[str], None] = None,
        max_files: Optional[int] = None,
    ) -> None:
        if isinstance(accept, str):
            accept = accept.split(",")
        tokens = tuple(t.strip().lower() for t in accept or () if t.strip())
        if max_files is not None and max_files < 1:
            raise ValueError("max_files must be 1 or more")
        object.__setattr__(
            self, "max_size", None if max_size is None else parse_size(max_size)
        )
        object.__setattr__(self, "accept", tokens)
        object.__setattr__(self, "max_files", max_files)

    def accepts(self, upload: Upload) -> bool:
        if not self.accept:
            return True
        name = upload.filename.lower()
        ctype = upload.content_type.split(";", 1)[0].strip().lower()
        for token in self.accept:
            if token.startswith("."):
                if name.endswith(token):
                    return True
            elif token.endswith("/*"):
                if ctype.startswith(token[:-1]):
                    return True
            elif ctype == token:
                return True
        return False

    def _check_one(self, upload: Upload) -> None:
        if self.max_size is not None and upload.size > self.max_size:
            raise PydanticCustomError(
                "file_too_large",
                "Choose a file no larger than {max_size}",
                {"max_size": format_size(self.max_size), "filename": upload.filename},
            )
        if not self.accepts(upload):
            raise PydanticCustomError(
                "file_type",
                "Choose a file of type {accept}",
                {"accept": ", ".join(self.accept), "filename": upload.filename},
            )

    def _check(self, value: Any) -> Any:
        if isinstance(value, Upload):
            self._check_one(value)
        elif isinstance(value, (list, tuple)):
            if self.max_files is not None and len(value) > self.max_files:
                raise PydanticCustomError(
                    "too_many_files",
                    "Choose at most {max_files} files",
                    {"max_files": self.max_files},
                )
            for item in value:
                if isinstance(item, Upload):
                    self._check_one(item)
        return value

    def __get_pydantic_core_schema__(self, source: Any, handler: Any) -> Any:
        return core_schema.no_info_after_validator_function(
            self._check, handler(source)
        )

    def __get_pydantic_json_schema__(self, schema: Any, handler: Any) -> Any:
        out = handler(schema)
        self._describe(handler.resolve_ref_schema(out))
        return out

    def _describe(self, schema: Any) -> None:
        if not isinstance(schema, dict):
            return
        if schema.get("format") == "binary":
            if self.accept:
                schema["x-accept"] = ",".join(self.accept)
            if self.max_size is not None:
                schema["x-max-size"] = self.max_size
        if schema.get("type") == "array":
            if self.max_files is not None:
                schema["maxItems"] = min(
                    self.max_files, schema.get("maxItems", self.max_files)
                )
            self._describe(schema.get("items"))
        for option in schema.get("anyOf", ()):
            self._describe(option)
