import re


def preprocess_python_code(code: str) -> str:
    """
    Pre-process Python code to handle custom PyWire syntax ($var -> var.value).

    This function replaces usage of the '$' prefix on identifiers with the '.value' suffix access,
    which is the standard way to access PyWire 'wire' primitives.

    Example:
        $count += 1  ->  count.value += 1

    It respects Python string boundaries (single and triple quoted) to avoid replacing
    text inside strings.
    """
    # Pattern matches:
    # Group 1: Strings (Triple double, Triple single, Double, Single)
    # Group 2: The $ token
    # Group 3: The identifier

    # We use non-capturing groups (?:...) for internal parts of string patterns to verify content
    # Triple quoted strings can contain newlines ([\s\S]*?)
    # Single quoted strings cannot contain unescaped newlines (not matching \n)

    pattern = (
        r"(\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|"  # Triple quoted strings
        r"\"(?:\\.|[^\\\"\n])*\"|'(?:\\.|[^\\'\n])*')|"  # Single quoted strings
        r"(\$)([a-zA-Z_]\w*)"  # The syntax we want to replace
    )

    def replacer(match):
        # If it matched a string (Group 1), return it unchanged
        if match.group(1):
            return match.group(1)

        # If it matched our syntax ($ + Identifier)
        if match.group(2) and match.group(3):
            return f"{match.group(3)}.value"

        return match.group(0)

    return re.sub(pattern, replacer, code, flags=re.MULTILINE)
