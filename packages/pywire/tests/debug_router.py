import re


def replace_param(match: re.Match) -> str:
    print(f"MATCH: {match.group(0)} -> {{{match.group(1)}}}")
    return f"{{{match.group(1)}}}"


url = "/projects/{pid:int}/{action}"
cleaned = re.sub(r":(\w+)(:\w+)?", replace_param, url)
print(f"AFTER 1st: {cleaned}")
cleaned = re.sub(r"\{(\w+)(:\w+)?\}", replace_param, cleaned)
print(f"AFTER 2nd: {cleaned}")

try:
    print(f"FORMATTED: {cleaned.format(pid=42, action='view')}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
