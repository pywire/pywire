"""Rule registry.

Rules register themselves at import time via :func:`register_rule`. The
registry is a module-level dict keyed by rule code.
"""

from __future__ import annotations

from typing import Dict, Type

from pywire_parser.analysis.rules.base import Rule

_REGISTRY: Dict[str, Type[Rule]] = {}


def register_rule(rule_cls: Type[Rule]) -> Type[Rule]:
    """Class decorator that adds a rule to the registry."""
    code = rule_cls.code
    if code in _REGISTRY and _REGISTRY[code] is not rule_cls:
        raise ValueError(f"Duplicate rule code: {code}")
    _REGISTRY[code] = rule_cls
    return rule_cls


def get_rule(code: str) -> Type[Rule]:
    return _REGISTRY[code]


def all_rule_codes() -> list[str]:
    return sorted(_REGISTRY.keys())


def rules_by_code(codes: list[str] | None = None) -> list[Rule]:
    """Instantiate rules. Pass ``None`` for all registered rules."""
    if codes is None:
        codes = all_rule_codes()
    return [_REGISTRY[c]() for c in codes if c in _REGISTRY]
