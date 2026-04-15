"""Persistent CLI settings stored in .pywire/settings.toml."""

import tomllib
from pathlib import Path
from typing import Any, Optional

try:
    import rich_click as click
    from rich.console import Console
except ImportError:
    import sys

    print(
        "Error: pywire CLI requires additional dependencies.\n"
        "Install them with: uv add pywire[cli]  (or: pip install pywire[cli])",
        file=sys.stderr,
    )
    sys.exit(1)

console = Console()

SETTINGS_DIR = Path(".pywire")
SETTINGS_FILE = SETTINGS_DIR / "settings.toml"

# Valid setting keys and their accepted values
VALID_SETTINGS: dict[str, dict[str, Any]] = {
    "tui": {
        "type": "bool",
        "on_values": {"on", "true", "1", "yes"},
        "off_values": {"off", "false", "0", "no"},
        "description": "Enable TUI dashboard for dev server",
    },
}


def _read_settings() -> dict[str, Any]:
    """Read settings from .pywire/settings.toml, returning empty dict if missing."""
    if not SETTINGS_FILE.exists():
        return {}
    with open(SETTINGS_FILE, "rb") as f:
        data = tomllib.load(f)
    return data.get("cli", {})


def _write_settings(settings: dict[str, Any]) -> None:
    """Write settings to .pywire/settings.toml using simple TOML formatting."""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["[cli]"]
    for key, value in sorted(settings.items()):
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        else:
            lines.append(f"{key} = {value}")
    SETTINGS_FILE.write_text("\n".join(lines) + "\n")


def get_setting(key: str) -> Optional[Any]:
    """Get a single setting value, or None if not set."""
    return _read_settings().get(key)


def _parse_bool_value(key: str, value: str) -> bool:
    """Parse a string value into a boolean for the given setting key."""
    meta = VALID_SETTINGS[key]
    lower = value.lower()
    if lower in meta["on_values"]:
        return True
    if lower in meta["off_values"]:
        return False
    on = ", ".join(sorted(meta["on_values"]))
    off = ", ".join(sorted(meta["off_values"]))
    raise click.BadParameter(
        f"Invalid value '{value}' for '{key}'. Use one of: {on} (enable) or {off} (disable)."
    )


@click.command(name="config")
@click.argument("key", required=False)
@click.argument("value", required=False)
def config_command(key: Optional[str], value: Optional[str]) -> None:
    """View or update persistent CLI settings (.pywire/settings.toml).

    \b
    Examples:
      pywire config          Show all settings
      pywire config tui      Show TUI setting
      pywire config tui on   Enable TUI by default
      pywire config tui off  Disable TUI by default
    """
    if key is None:
        # Show all settings
        settings = _read_settings()
        if not settings:
            console.print("[dim]No settings configured yet.[/]")
            console.print(
                "[dim]Available settings:[/] "
                + ", ".join(f"[cyan]{k}[/]" for k in sorted(VALID_SETTINGS))
            )
            return
        for k, v in sorted(settings.items()):
            console.print(f"[cyan]{k}[/] = [bold]{v}[/]")
        return

    if key not in VALID_SETTINGS:
        valid = ", ".join(sorted(VALID_SETTINGS))
        raise click.BadParameter(
            f"Unknown setting '{key}'. Valid settings: {valid}",
            param_hint="KEY",
        )

    if value is None:
        # Show single setting
        current = get_setting(key)
        if current is None:
            console.print(f"[cyan]{key}[/] = [dim]<not set>[/]")
        else:
            console.print(f"[cyan]{key}[/] = [bold]{current}[/]")
        return

    # Set value
    meta = VALID_SETTINGS[key]
    if meta["type"] == "bool":
        parsed = _parse_bool_value(key, value)
    else:
        parsed = value

    settings = _read_settings()
    settings[key] = parsed
    _write_settings(settings)
    console.print(f"[cyan]{key}[/] = [bold]{parsed}[/]")
