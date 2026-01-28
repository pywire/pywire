"""Attribute code generators."""

from pywire.compiler.codegen.attributes.base import AttributeCodegen
from pywire.compiler.codegen.attributes.events import EventAttributeCodegen

__all__ = ["AttributeCodegen", "EventAttributeCodegen"]
