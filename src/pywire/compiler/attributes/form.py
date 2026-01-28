"""Form attribute parsers for $model and $field."""

from typing import Optional

from pywire.compiler.ast_nodes import ModelAttribute
from pywire.compiler.attributes.base import AttributeParser


class ModelAttributeParser(AttributeParser):
    """Parses $model={ModelClassName} attribute for Pydantic binding."""

    PREFIX = "$model"

    def can_parse(self, attr_name: str) -> bool:
        """Check if attribute is $model."""
        return attr_name == "$model"

    def parse(
        self, attr_name: str, attr_value: str, line: int, col: int
    ) -> Optional[ModelAttribute]:
        """Parse $model={ClassName} attribute."""
        if attr_name != "$model":
            return None

        model_name = attr_value.strip().strip("\"'")
        if model_name.startswith("{") and model_name.endswith("}"):
            model_name = model_name[1:-1].strip()
        if not model_name:
            return None

        return ModelAttribute(
            name=attr_name, value=attr_value, model_name=model_name, line=line, column=col
        )
