"""Two kinds of model behind two small HTTP clients.

- Groq runs a chat model (gpt-oss) that *writes*: it drafts the form's
  wording and options as JSON that must match a schema.
- Jev (TypeSafe's System One API) *decides*: it takes some state and typed
  questions (yes/no, pick one, score) and returns probabilities, not text.

Both use one ``httpx.AsyncClient`` per call, which works the same under
uvicorn and in Cloudflare Python Workers. Pass ``transport`` to test them
without the network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import httpx

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
JEV_URL = "https://api.typesafe.ai/v1/systemone"


class AIError(Exception):
    """A model call failed; the message is safe to show."""


OUT_OF_USAGE = (
    "The author of this demo has run out of AI usage for now. Please try again later."
)


class OutOfUsage(AIError):
    """Rate limited, out of credits, or the key was refused (HTTP 401, 402,
    403, 429). The visitor can't fix any of these, so they all read the same:
    the demo's author is out of usage, try again later."""

    def __init__(self, service: str, status: int, retry_after: Optional[float]) -> None:
        self.service = service
        self.status = status
        self.retry_after = retry_after
        super().__init__(OUT_OF_USAGE)


def _retry_after(response: httpx.Response) -> Optional[float]:
    try:
        return float(response.headers.get("retry-after", ""))
    except ValueError:
        return None


def _check(service: str, response: httpx.Response) -> Any:
    if response.status_code in (401, 402, 403, 429):
        raise OutOfUsage(service, response.status_code, _retry_after(response))
    if response.status_code >= 400:
        raise AIError(f"{service} returned an error ({response.status_code}).")
    try:
        return response.json()
    except ValueError:
        raise AIError(f"{service} returned something that isn't JSON.") from None


@dataclass
class Groq:
    api_key: str
    transport: Optional[httpx.AsyncBaseTransport] = None
    timeout: float = 30.0

    async def json(
        self,
        model: str,
        system: str,
        user: str,
        schema_name: str,
        schema: Mapping[str, Any],
        *,
        max_tokens: int = 2000,
    ) -> dict:
        """One chat completion whose reply must match ``schema`` (strict)."""
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
            # gpt-oss reasons before it answers. Keep that short: the free
            # plan counts reasoning tokens against the per-minute budget.
            "reasoning_effort": "low",
            "max_completion_tokens": max_tokens,
            "temperature": 0.3,
        }
        async with httpx.AsyncClient(
            transport=self.transport, timeout=self.timeout
        ) as client:
            try:
                response = await client.post(
                    GROQ_URL,
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
            except httpx.HTTPError:
                raise AIError("Couldn't reach Groq.") from None
        data = _check("Groq", response)
        try:
            return json.loads(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError):
            raise AIError("Groq's reply didn't match the form schema.") from None


@dataclass
class Jev:
    api_key: str
    model: str = "jev-latest"
    transport: Optional[httpx.AsyncBaseTransport] = None
    timeout: float = 20.0

    async def ask(self, state: Any, questions: Mapping[str, Any]) -> dict:
        """Evaluate ``state`` against typed questions; returns the answers by id."""
        body = {"state": state, "model": self.model, "questions": dict(questions)}
        async with httpx.AsyncClient(
            transport=self.transport, timeout=self.timeout
        ) as client:
            try:
                response = await client.post(
                    JEV_URL,
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
            except httpx.HTTPError:
                raise AIError("Couldn't reach TypeSafe.") from None
        data = _check("TypeSafe", response)
        answers = data.get("answers") if isinstance(data, dict) else None
        if not isinstance(answers, dict) or set(questions) - set(answers):
            raise AIError("TypeSafe's reply was missing answers.")
        return answers


def noul(answer: Any) -> float:
    """The yes probability of a noul answer, 0.5 when it's malformed."""
    value = answer.get("noul") if isinstance(answer, dict) else None
    return float(value) if isinstance(value, (int, float)) else 0.5
