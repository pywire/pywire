"""Form builder: describe a form in a sentence, get a working pywire form.

``services()`` and ``limiter`` are module globals so tests can swap in fake
clients and a fresh limiter.
"""

from __future__ import annotations

from formbuilder.ai import Groq, Jev
from formbuilder.limits import MemoryLimiter
from formbuilder.pipeline import Services
from formbuilder.settings import settings

limiter = MemoryLimiter()


def _default_services() -> Services:
    return Services(
        groq=Groq(settings.groq_api_key),
        jev=Jev(settings.typesafe_api_key, model=settings.jev_model),
        writer_model=settings.writer_model,
        helper_model=settings.helper_model,
    )


services = _default_services
