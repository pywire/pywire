def preprocess_python_code(code: str) -> str:
    """
    No-op: Legacy preprocessor for $var syntax.

    This function used to replace $var with var.value, but that syntax is now removed.
    It returns the code unchanged.
    """
    return code
