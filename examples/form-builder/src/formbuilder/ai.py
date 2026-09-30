"""Two kinds of model behind two small HTTP clients.

- OpenRouter runs a chat model that *writes*: it drafts the form's wording
  and options as JSON that must match a schema. It tries a list of models in
  order, free ones first, so a free model going away or hitting its limit
  falls through to the next.
- Jev (TypeSafe's System One API) *decides*: it takes some state and typed
  questions (yes/no, pick one, score) and returns probabilities, not text.

Both use one ``httpx.AsyncClient`` per call, which works the same under
uvicorn and in Cloudflare Python Workers. Pass ``transport`` to test them
without the network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
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


def _reply_json(data: Any) -> dict:
    """The JSON object in a chat reply, allowing for a ```json fence."""
    content = data["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("not an object")
    return value


@dataclass
class OpenRouter:
    api_key: str
    transport: Optional[httpx.AsyncBaseTransport] = None
    timeout: float = 30.0

    async def json(
        self,
        models: Sequence[str],
        system: str,
        user: str,
        schema_name: str,
        schema: Mapping[str, Any],
        *,
        max_tokens: int = 2000,
    ) -> dict:
        """One chat completion whose reply must match ``schema``.

        Tries ``models`` in order. A model that's rate limited, gone, down or
        answers with something that isn't JSON passes the request on to the
        next. A refused key stops at once; if every model was out of usage,
        so is the demo.
        """
        out_of_usage: Optional[OutOfUsage] = None
        async with httpx.AsyncClient(
            transport=self.transport, timeout=self.timeout
        ) as client:
            for model in models:
                body = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema_name,
                            "strict": True,
                            "schema": schema,
                        },
                    },
                    # Reasoning models think before they answer; keep it
                    # short so a build stays quick and cheap.
                    "reasoning": {"effort": "low", "exclude": True},
                    "max_tokens": max_tokens,
                    "temperature": 0.3,
                }
                try:
                    response = await client.post(
                        OPENROUTER_URL,
                        json=body,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "HTTP-Referer": "https://demo.pywire.dev/form-builder/",
                            "X-Title": "pywire form builder",
                        },
                    )
                    data = _check("OpenRouter", response)
                    return _reply_json(data)
                except OutOfUsage as error:
                    if error.status in (401, 403):
                        raise
                    out_of_usage = error
                except (AIError, httpx.HTTPError):
                    pass
                except (KeyError, IndexError, TypeError, ValueError):
                    pass
        if out_of_usage is not None:
            raise out_of_usage
        raise AIError("None of the models could write the form. Try again.")


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
