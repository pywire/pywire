"""Auth directive parser."""

import ast
import re
from typing import List, Optional, Tuple

from pywire_parser.ast_nodes import AuthDirective
from pywire_parser.directives.base import DirectiveParser


class AuthDirectiveParser(DirectiveParser):
    """Parses !auth directive.

    Forms:
        !auth                                        # require authenticated user
        !auth "PolicyName"                           # named policy
        !auth {"policy":"X","claims":[("t","v"), ...],"redirect":"/login"}

    Inside the dict, ``claims`` may be a list where each item is either:
      - ``"type"`` — require a claim of that type, any value
      - ``("type", "value")`` or ``["type", "value"]`` — require the exact claim
    """

    PATTERN = re.compile(r"^!auth(?:\s+(.+))?$", re.DOTALL)

    def can_parse(self, line: str) -> bool:
        stripped = line.strip()
        return stripped == "!auth" or stripped.startswith("!auth ")

    def parse(self, line: str, line_num: int, col_num: int) -> Optional[AuthDirective]:
        match = self.PATTERN.match(line.strip())
        if not match:
            return None

        args = match.group(1)
        if args is None or not args.strip():
            return AuthDirective(name="auth", line=line_num, column=col_num)

        args_str = args.strip()

        try:
            expr_ast = ast.parse(args_str, mode="eval")
        except (SyntaxError, ValueError):
            return None

        body = expr_ast.body

        if isinstance(body, ast.Constant) and isinstance(body.value, str):
            return AuthDirective(
                name="auth",
                policy=body.value,
                line=line_num,
                column=col_num,
            )

        if isinstance(body, ast.Dict):
            return self._parse_dict(body, line_num, col_num)

        return None

    def _parse_dict(
        self, body: ast.Dict, line_num: int, col_num: int
    ) -> Optional[AuthDirective]:
        policy: Optional[str] = None
        claims: Optional[List[Tuple[str, str]]] = None
        redirect: Optional[str] = None

        for k, v in zip(body.keys, body.values):
            if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
                return None
            key = k.value

            if key == "policy":
                if not isinstance(v, ast.Constant) or not isinstance(v.value, str):
                    return None
                policy = v.value
            elif key == "redirect":
                if not isinstance(v, ast.Constant) or not isinstance(v.value, str):
                    return None
                redirect = v.value
            elif key == "claims":
                if not isinstance(v, ast.List):
                    return None
                parsed = self._parse_claims_list(v)
                if parsed is None:
                    return None
                claims = parsed
            else:
                return None

        return AuthDirective(
            name="auth",
            policy=policy,
            claims=claims,
            redirect=redirect,
            line=line_num,
            column=col_num,
        )

    def _parse_claims_list(self, v: ast.List) -> Optional[List[Tuple[str, str]]]:
        parsed: List[Tuple[str, str]] = []
        for item in v.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                parsed.append((item.value, ""))
                continue
            if isinstance(item, (ast.List, ast.Tuple)):
                if len(item.elts) != 2:
                    return None
                if not all(
                    isinstance(e, ast.Constant) and isinstance(e.value, str)
                    for e in item.elts
                ):
                    return None
                parsed.append((item.elts[0].value, item.elts[1].value))  # type: ignore[attr-defined]
                continue
            return None
        return parsed
