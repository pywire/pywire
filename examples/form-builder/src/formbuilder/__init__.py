"""Form builder: describe a form in a sentence, get a working pywire form.

``services()`` and ``limiter`` are module globals so tests can swap in fake
clients and a fresh limiter.
"""

from __future__ import annotations

from formbuilder.ai import Jev, OpenRouter
from formbuilder.limits import MemoryLimiter
from formbuilder.pipeline import Services
from formbuilder.settings import settings

limiter = MemoryLimiter()


def _default_services() -> Services:
    return Services(
        writer=OpenRouter(settings.openrouter_api_key),
        jev=Jev(settings.typesafe_api_key, model=settings.jev_model),
        writer_models=settings.writer_models,
    )


services = _default_services
