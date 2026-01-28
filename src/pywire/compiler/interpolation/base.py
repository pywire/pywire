"""Base interpolation parser."""

from abc import ABC, abstractmethod
from typing import List, Union

from pywire.compiler.ast_nodes import InterpolationNode


class InterpolationParser(ABC):
    """Base class for parsing interpolations - can swap Jinja for custom later."""

    @abstractmethod
    def parse(self, text: str, line: int, col: int) -> List[Union[str, InterpolationNode]]:
        """
        Parse text with interpolations into mix of strings and InterpolationNodes.
        Returns: ['Hello, ', InterpolationNode(expr='name'), '!']
        """
        pass

    @abstractmethod
    def compile(self, text: str) -> str:
        """
        Compile to Python code for runtime.
        'Hello {name}!' → f'Hello {self.name}!'
        """
        pass
