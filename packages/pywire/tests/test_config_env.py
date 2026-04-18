"""Tests for pywire.config.env."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pywire.config import env, reload


class TestEnvHelper(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._saved)
        reload()  # reset cache

    def test_missing_returns_none(self) -> None:
        os.environ.pop("PW_TEST_MISSING", None)
        self.assertIsNone(env("PW_TEST_MISSING"))

    def test_missing_with_default(self) -> None:
        os.environ.pop("PW_TEST_MISSING", None)
        self.assertEqual(env("PW_TEST_MISSING", default="fallback"), "fallback")

    def test_required_missing_raises(self) -> None:
        os.environ.pop("PW_TEST_REQUIRED", None)
        with self.assertRaises(RuntimeError):
            env("PW_TEST_REQUIRED", required=True)

    def test_string_read(self) -> None:
        os.environ["PW_TEST_VAR"] = "hello"
        self.assertEqual(env("PW_TEST_VAR"), "hello")

    def test_cast_bool_truthy(self) -> None:
        for v in ("1", "true", "True", "yes", "on", "t"):
            os.environ["PW_TEST_BOOL"] = v
            self.assertTrue(env("PW_TEST_BOOL", cast=bool), v)

    def test_cast_bool_falsy(self) -> None:
        for v in ("0", "false", "no", "off", ""):
            os.environ["PW_TEST_BOOL"] = v
            self.assertFalse(env("PW_TEST_BOOL", cast=bool), v)

    def test_cast_int(self) -> None:
        os.environ["PW_TEST_INT"] = "42"
        self.assertEqual(env("PW_TEST_INT", cast=int), 42)

    def test_cast_float(self) -> None:
        os.environ["PW_TEST_FLOAT"] = "3.14"
        self.assertEqual(env("PW_TEST_FLOAT", cast=float), 3.14)

    def test_cast_custom(self) -> None:
        os.environ["PW_TEST_CSV"] = "a,b,c"
        self.assertEqual(
            env("PW_TEST_CSV", cast=lambda s: s.split(",")), ["a", "b", "c"]
        )


class TestDotenvCascade(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = dict(os.environ)
        self._cwd = os.getcwd()

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        os.environ.clear()
        os.environ.update(self._saved)
        reload()

    def _clean(self, *keys: str) -> None:
        for k in keys:
            os.environ.pop(k, None)

    def test_loads_dot_env(self) -> None:
        self._clean("PW_DOTENV_A", "PW_DOTENV_B")
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / ".env").write_text("PW_DOTENV_A=from_env\n")
            os.chdir(path)
            reload(path)
            self.assertEqual(env("PW_DOTENV_A"), "from_env")

    def test_real_env_wins_over_dotenv(self) -> None:
        self._clean("PW_DOTENV_WIN")
        os.environ["PW_DOTENV_WIN"] = "from_shell"
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / ".env").write_text("PW_DOTENV_WIN=from_file\n")
            reload(path)
            self.assertEqual(env("PW_DOTENV_WIN"), "from_shell")

    def test_env_local_overrides_env(self) -> None:
        self._clean("PW_DOTENV_OVR")
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / ".env").write_text("PW_DOTENV_OVR=base\n")
            (path / ".env.local").write_text("PW_DOTENV_OVR=local\n")
            reload(path)
            self.assertEqual(env("PW_DOTENV_OVR"), "local")

    def test_mode_env_highest(self) -> None:
        self._clean("PW_DOTENV_MODE")
        os.environ["PYWIRE_MODE"] = "dev"
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / ".env").write_text("PW_DOTENV_MODE=base\n")
            (path / ".env.local").write_text("PW_DOTENV_MODE=local\n")
            (path / ".env.dev").write_text("PW_DOTENV_MODE=dev_mode\n")
            reload(path)
            self.assertEqual(env("PW_DOTENV_MODE"), "dev_mode")

    def test_ignores_comments_and_blank_lines(self) -> None:
        self._clean("PW_DOTENV_X")
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / ".env").write_text(
                '# a comment\n\n  # indented comment\nPW_DOTENV_X="quoted value"\n'
            )
            reload(path)
            self.assertEqual(env("PW_DOTENV_X"), "quoted value")

    def test_export_prefix_stripped(self) -> None:
        self._clean("PW_DOTENV_EXPORT")
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / ".env").write_text("export PW_DOTENV_EXPORT=yes\n")
            reload(path)
            self.assertEqual(env("PW_DOTENV_EXPORT"), "yes")


if __name__ == "__main__":
    unittest.main()
