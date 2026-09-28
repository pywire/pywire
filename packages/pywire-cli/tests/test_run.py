"""`pywire run` passes server options through to Uvicorn."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pywire_cli.main import cli


@pytest.mark.parametrize(
    ("args", "deflate"), [([], True), (["--no-ws-deflate"], False)]
)
def test_ws_deflate_flag(args: list[str], deflate: bool) -> None:
    with (
        patch("pywire_cli.main.import_app"),
        patch("uvicorn.run") as run,
    ):
        result = CliRunner().invoke(cli, ["run", "main:app", "--workers", "1", *args])

    assert result.exit_code == 0, result.output
    assert run.call_args.kwargs["ws_per_message_deflate"] is deflate
