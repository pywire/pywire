from typing import Any

import pytest
from pywire.runtime.helpers import ensure_async_iterator


@pytest.mark.asyncio
async def test_ensure_async_iterator_async_gen() -> None:
    """Verify helper works with actual async generators."""

    async def async_gen() -> Any:
        yield 1
        yield 2

    gen = async_gen()
    results = []
    async for item in ensure_async_iterator(gen):
        results.append(item)
    assert results == [1, 2]


@pytest.mark.asyncio
async def test_ensure_async_iterator_non_iterable() -> None:
    """Verify helper behavior with non-iterable (should raise TypeError on iteration)."""
    with pytest.raises(TypeError):
        async for item in ensure_async_iterator(123):
            pass
