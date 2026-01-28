"""Compiler exceptions."""


class PyWireSyntaxError(Exception):
    """Raised when PyWire syntax is invalid."""

    def __init__(self, message: str, file_path: str = "", line: int = 0, column: int = 0):
        self.message = message
        self.file_path = file_path
        self.line = line
        self.column = column
        super().__init__(message)

    def __str__(self) -> str:
        if self.file_path and self.line:
            return f"{self.file_path}:{self.line}: {self.message}"
        return self.message
