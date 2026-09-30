"""Two tabs, one server process: shared state reaches both."""

from conftest import Session, handler, only_handler

import counter
import live


def test_a_vote_in_one_tab_updates_the_other(client):
    live.reset_votes()
    name, args = handler(client.get("/").text, "click", "Payments")
    with (
        client.websocket_connect("/_pywire/ws") as ws_a,
        client.websocket_connect("/_pywire/ws") as ws_b,
    ):
        a, b = Session(ws_a, "/"), Session(ws_b, "/")
        a.drain()
        b.drain()

        assert "1 votes." in a.event(name, args)
        assert "1 votes." in b.html()  # pushed; B did nothing


def test_votes_for_unknown_options_are_refused(client):
    live.reset_votes()
    name, _ = handler(client.get("/").text, "click", "Payments")
    with client.websocket_connect("/_pywire/ws") as ws:
        tab = Session(ws, "/")
        tab.drain()
        # The page signs the arguments it renders: any other value is refused.
        tab.send({"type": "event", "handler": name, "data": {"args": {"arg0": "Nope"}}})
        assert tab.recv()["type"] in ("error", "error_trace")
        assert live.total_votes.value == 0


def test_presence_follows_open_tabs(client):
    with client.websocket_connect("/_pywire/ws") as ws_a:
        a = Session(ws_a, "/")
        a.drain()
        assert len(live.online) == 1
        with client.websocket_connect("/_pywire/ws") as ws_b:
            Session(ws_b, "/")
            assert "Here now (2)" in a.html()
        assert "Here now (1)" in a.html()  # B closed: @unmount ran
        assert len(live.online) == 1


def test_chat_messages_reach_everyone(client):
    page = client.get("/chat").text
    bind, send = only_handler(page, "input"), only_handler(page, "submit")
    with (
        client.websocket_connect("/_pywire/ws") as ws_a,
        client.websocket_connect("/_pywire/ws") as ws_b,
    ):
        a, b = Session(ws_a, "/chat"), Session(ws_b, "/chat")
        a.drain()
        b.drain()
        a.event(bind, value="hello")
        a.event(send)
        assert "hello" in b.html()
        assert live.messages[-1]["text"] == "hello"


def test_the_lock_keeps_every_increment(client):
    page = client.get("/race").text
    unsafe, _ = handler(page, "click", "+10 without a lock")
    locked, _ = handler(page, "click", "+10 with a lock")
    with client.websocket_connect("/_pywire/ws") as ws:
        tab = Session(ws, "/race")
        tab.drain()

        tab.event(unsafe)
        assert counter.saved.value < 10  # lost updates

        before = counter.saved.value
        tab.event(locked)
        assert counter.saved.value == before + 10
