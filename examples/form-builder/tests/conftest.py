"""Test setup: fake OpenRouter and Jev, and one browser tab driver per mode.

The fakes answer through ``httpx.MockTransport``, so the real clients (URL,
headers, body, error handling) run unchanged; only the network is fake.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import anyio
import httpx
import msgpack
import pytest
from starlette.testclient import TestClient

os.environ.setdefault("PYWIRE_SECRET_KEY", "test-only-" + "x" * 32)
os.environ["OPENROUTER_API_KEY"] = "test-openrouter"
os.environ["TYPESAFE_API_KEY"] = "test-typesafe"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# What the fake writer drafts for any request: one field of each shape.
DRAFT = {
    "title": "Wedding RSVP",
    "intro": "Let us know if you can make it.",
    "fields": [
        {"name": "full_name", "label": "Your name", "help": "", "options": []},
        {"name": "email", "label": "Email", "help": "", "options": []},
        {"name": "guests", "label": "Guests", "help": "Including you", "options": []},
        {"name": "meal", "label": "Meal", "help": "", "options": []},
        {"name": "dietary", "label": "Dietary needs", "help": "",
         "options": ["Vegetarian", "Vegan", "Gluten free"]},
        {"name": "notes", "label": "Anything else?", "help": "", "options": []},
        {"name": "agree", "label": "I'll confirm by June 1", "help": "", "options": []},
    ],
}  # fmt: skip

KINDS = {
    "full_name": ("text", 0.93),
    "email": ("email", 0.97),
    "guests": ("integer", 0.9),
    "meal": ("choice", 0.81),  # no options drafted: triggers the options step
    "dietary": ("multi_choice", 0.88),
    "notes": ("long_text", 0.45),  # an "unsure" decision
    "agree": ("checkbox", 0.9),
}
REQUIRED = {"full_name", "email", "guests", "meal", "agree"}


class FakeAI:
    """Answers OpenRouter and Jev like the real APIs; records every call."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.failure: Optional[httpx.Response] = None
        self.overrides: Dict[str, Any] = {}
        # Per OpenRouter model: a response to send instead, or "not json".
        self.models: Dict[str, Any] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        service = "jev" if "typesafe" in request.url.host else "openrouter"
        self.calls.append({"service": service, "body": body})
        if self.failure is not None:
            return self.failure
        if service == "jev":
            return httpx.Response(200, json=self._jev(body))
        broken = self.models.get(body["model"])
        if isinstance(broken, httpx.Response):
            return broken
        if broken == "not json":
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "Sure! Here it is"}}]}
            )
        name = body["response_format"]["json_schema"]["name"]
        content = self.overrides.get(name) or self._writer(name, body)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(content)}}]}
        )

    def _jev(self, body: dict) -> dict:
        answers: Dict[str, Any] = {}
        for key, question in body["questions"].items():
            if key in self.overrides:
                answers[key] = self.overrides[key]
            elif key == "is_form":
                answers[key] = {"type": "noul", "noul": 0.97}
            elif key in ("sensitive", "abusive"):
                answers[key] = {"type": "noul", "noul": 0.02}
            elif key.startswith("kind."):
                name = key.split(".", 1)[1]
                kind, confidence = KINDS.get(name, ("text", 0.7))
                answers[key] = {
                    "type": "choice",
                    "choice": kind,
                    "probabilities": {kind: confidence},
                    "confidence": confidence,
                }
            elif key.startswith("required."):
                name = key.split(".", 1)[1]
                answers[key] = {
                    "type": "noul",
                    "noul": 0.9 if name in REQUIRED else 0.1,
                }
            else:
                raise AssertionError(f"unexpected question {key}")
        return {"model": "jev-test", "answers": answers, "usage": {}}

    def _writer(self, name: str, body: dict) -> dict:
        if name == "form":
            return DRAFT
        if name == "options":
            return {"fields": [{"name": "meal", "options": ["Beef", "Fish", "Veg"]}]}
        if name == "answers":
            return {
                "answers": [
                    {"name": "full_name", "values": ["Ada Lovelace"]},
                    {"name": "email", "values": ["ada@example.com"]},
                    {"name": "guests", "values": ["2"]},
                    {"name": "meal", "values": ["Fish"]},
                    {"name": "dietary", "values": ["Vegan", "Not an option"]},
                    {"name": "notes", "values": ["See you there"]},
                    {"name": "agree", "values": ["yes"]},
                ]
            }
        raise AssertionError(f"unexpected schema {name}")


@pytest.fixture()
def fake_ai(monkeypatch) -> FakeAI:
    import formbuilder
    from formbuilder.ai import Jev, OpenRouter
    from formbuilder.limits import MemoryLimiter
    from formbuilder.pipeline import Services

    fake = FakeAI()
    transport = httpx.MockTransport(fake)
    services = Services(
        writer=OpenRouter("test-openrouter", transport=transport),
        jev=Jev("test-typesafe", transport=transport),
        writer_models=("free/model:free", "paid/model"),
    )
    monkeypatch.setattr(formbuilder, "services", lambda: services)
    monkeypatch.setattr(formbuilder, "limiter", MemoryLimiter())
    return fake


@pytest.fixture(scope="session")
def apps():
    from main import create_app

    clients = {}
    for mode in ("stateless", "live"):
        client = TestClient(create_app(stateless=mode == "stateless"))
        clients[mode] = client.__enter__()
    yield clients
    for client in clients.values():
        client.__exit__(None, None, None)


class Tab:
    """One browser tab on ``/``, in either mode.

    ``page`` accumulates every piece of HTML the tab has received, newest
    last, so handler names are found the way the browser would see them.
    """

    def __init__(self, client: TestClient, stateless: bool) -> None:
        self.client = client
        self.stateless = stateless
        client.cookies.clear()
        response = client.get("/")
        assert response.status_code == 200
        self.page = response.text
        self.snapshot = ""
        if stateless:
            self.snapshot = self.page.split('_pywire_snapshot" type="text/plain">')[
                1
            ].split("</script>")[0]
        else:
            self.ws = client.websocket_connect("/_pywire/ws").__enter__()
            assert self._recv()["type"] == "init"
            self._send({"type": "init", "path": "/"})
            assert self._recv()["type"] == "init_ack"

    # -- transport ------------------------------------------------------------

    def _send(self, message: dict) -> None:
        self.ws.send_bytes(msgpack.packb(message))

    def _recv(self, timeout: float = 3.0) -> dict:
        async def receive() -> Any:
            with anyio.fail_after(timeout):
                return await self.ws._send_rx.receive()

        while True:
            data = msgpack.unpackb(self.ws.portal.call(receive)["bytes"], raw=False)
            if data["type"] != "console":
                return data

    def fire(self, handler: str, args: Optional[str] = None, **data: Any) -> str:
        """Send one event and return the HTML of the reply.

        ``args`` is the signed ``data-pw-args-*`` token the element rendered.
        """
        payload = {**data}
        if "formData" in payload:
            payload.setdefault("type", "submit")
        if args:
            payload["args"] = args
        if self.stateless:
            response = self.client.post(
                "/_pywire/stateless",
                content=msgpack.packb(
                    {
                        "path": "/",
                        "handler": handler,
                        "data": payload,
                        "snapshot": self.snapshot,
                    }
                ),
                headers={"Content-Type": "application/x-msgpack"},
            )
            reply = msgpack.unpackb(response.content, raw=False)
            assert response.status_code == 200, reply
            self.snapshot = reply.get("snapshot", self.snapshot)
        else:
            self._send(
                {"type": "event", "handler": handler, "path": "/", "data": payload}
            )
            reply = self._recv()
            assert reply["type"] == "update", reply
        html = reply.get("html") or "".join(
            r.get("html", "") for r in reply.get("regions", [])
        )
        self.page += html
        return html

    def close(self) -> None:
        if not self.stateless:
            self.ws.__exit__(None, None, None)

    # -- finding things ---------------------------------------------------------

    def handler(self, event: str, label: str) -> tuple[str, Optional[str]]:
        """Handler and signed args of the latest ``@event`` element with this text."""
        found = None
        for match in re.finditer(r"<(\w+)([^>]*)>([^<]*)(?=<)", self.page):
            attrs, text = match.group(2), match.group(3)
            name = re.search(rf'data-on-{event}="([^"]+)"', attrs)
            if name and text.strip() == label:
                args = re.search(rf'data-pw-args-{event}="([^"]*)"', attrs)
                found = (name.group(1), args.group(1) if args else None)
        assert found, f"no @{event} element labelled {label!r}"
        return found

    def form(self, form_id: str) -> tuple[str, Dict[str, str]]:
        """Submit handler and hidden inputs of the latest ``<form id=...>``."""
        found = re.findall(
            rf'<form[^>]*\bid="{form_id}"[^>]*>.*?</form>', self.page, re.S
        )
        assert found, f"no form {form_id}"
        markup = found[-1]
        handler = re.search(r'data-on-submit="([^"]+)"', markup).group(1)
        hidden = {
            html_lib.unescape(n): html_lib.unescape(v)
            for n, v in re.findall(
                r'<input type="hidden" name="([^"]+)" value="([^"]*)"', markup
            )
        }
        return handler, hidden

    def submit(self, form_id: str, **fields: Any) -> str:
        handler, hidden = self.form(form_id)
        return self.fire(handler, formData={**hidden, **fields})

    def build(self, text: str, handler: str = "build", **data: Any) -> str:
        """Start a run and tick the poll until it's done; returns all HTML."""
        seen = self.fire(handler, formData=data or {"request": text})
        for _ in range(12):
            latest = seen[seen.rfind('<ol class="steps">') :]
            poll = re.search(r'data-pw-poll="([^"]+)"', latest)
            if not poll:
                return seen
            seen += self.fire(poll.group(1))
        raise AssertionError("the run didn't finish")


@pytest.fixture(params=["stateless", "live"])
def tab(request, apps, fake_ai) -> Any:
    t = Tab(apps[request.param], stateless=request.param == "stateless")
    yield t
    t.close()
