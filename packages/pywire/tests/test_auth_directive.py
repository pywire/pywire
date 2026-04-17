"""Tests for the !auth directive (parser + codegen)."""

import ast
import unittest

from pywire.compiler.ast_nodes import AuthDirective
from pywire.compiler.codegen.generator import CodeGenerator
from pywire.compiler.parser import PyWireParser


class TestAuthDirectiveParser(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = PyWireParser()

    def _parse(self, source: str) -> AuthDirective:
        parsed = self.parser.parse(source)
        self.assertEqual(len(parsed.directives), 1)
        directive = parsed.directives[0]
        assert isinstance(directive, AuthDirective)
        return directive

    def test_bare_auth(self) -> None:
        d = self._parse("!auth\n<div>secret</div>")
        self.assertIsNone(d.policy)
        self.assertIsNone(d.claims)
        self.assertIsNone(d.redirect)

    def test_string_policy(self) -> None:
        d = self._parse('!auth "AdminOnly"\n<div/>')
        self.assertEqual(d.policy, "AdminOnly")
        self.assertIsNone(d.claims)
        self.assertIsNone(d.redirect)

    def test_dict_policy_only(self) -> None:
        d = self._parse('!auth {"policy": "AdminOnly"}\n<div/>')
        self.assertEqual(d.policy, "AdminOnly")

    def test_dict_redirect_only(self) -> None:
        d = self._parse('!auth {"redirect": "/login"}\n<div/>')
        self.assertEqual(d.redirect, "/login")

    def test_dict_claims_type_only(self) -> None:
        d = self._parse('!auth {"claims": ["admin"]}\n<div/>')
        self.assertEqual(d.claims, [("admin", "")])

    def test_dict_claims_tuples(self) -> None:
        d = self._parse(
            '!auth {"claims": [("role", "admin"), ("tier", "pro")]}\n<div/>'
        )
        self.assertEqual(d.claims, [("role", "admin"), ("tier", "pro")])

    def test_dict_claims_lists(self) -> None:
        d = self._parse('!auth {"claims": [["role", "admin"]]}\n<div/>')
        self.assertEqual(d.claims, [("role", "admin")])

    def test_dict_full(self) -> None:
        d = self._parse(
            '!auth {"policy": "AdminOnly", "claims": [("role", "admin")], '
            '"redirect": "/login"}\n<div/>'
        )
        self.assertEqual(d.policy, "AdminOnly")
        self.assertEqual(d.claims, [("role", "admin")])
        self.assertEqual(d.redirect, "/login")


class TestAuthDirectiveCodegen(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = PyWireParser()
        self.generator = CodeGenerator()

    def _compile_source(self, source: str) -> str:
        parsed = self.parser.parse(source)
        module = self.generator.generate(parsed)
        return ast.unparse(module)

    def test_no_directive_emits_no_attrs(self) -> None:
        code = self._compile_source("<div>hi</div>")
        self.assertNotIn("__auth_required__", code)
        self.assertNotIn("__auth_policy__", code)
        self.assertNotIn("__auth_claims__", code)
        self.assertNotIn("__auth_redirect__", code)

    def test_bare_auth_emits_required_only(self) -> None:
        code = self._compile_source("!auth\n<div>hi</div>")
        self.assertIn("__auth_required__ = True", code)
        self.assertNotIn("__auth_policy__", code)
        self.assertNotIn("__auth_claims__", code)
        self.assertNotIn("__auth_redirect__", code)

    def test_policy_emits_required_and_policy(self) -> None:
        code = self._compile_source('!auth "AdminOnly"\n<div/>')
        self.assertIn("__auth_required__ = True", code)
        self.assertIn("__auth_policy__ = 'AdminOnly'", code)

    def test_full_emits_all_attrs(self) -> None:
        code = self._compile_source(
            '!auth {"policy": "AdminOnly", "claims": [("role", "admin")], '
            '"redirect": "/login"}\n<div/>'
        )
        self.assertIn("__auth_required__ = True", code)
        self.assertIn("__auth_policy__ = 'AdminOnly'", code)
        self.assertIn("__auth_claims__ = [('role', 'admin')]", code)
        self.assertIn("__auth_redirect__ = '/login'", code)


if __name__ == "__main__":
    unittest.main()
