"""Pages over pywire's WebSocket: access checks, and live updates from any source."""

from taskboard import identity


def _board(user, name="Launch", invite=()):
    invites = [{"email": u.email} for u in invite]
    response = user.api(
        "POST",
        "/api/boards",
        json={"basics": {"name": name}, "team": {"invites": invites}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_pages_need_a_session(client):
    client.cookies.clear()
    response = client.get("/boards", follow_redirects=False)
    assert response.status_code in (302, 303, 307)
    assert response.headers["location"].startswith("/login")


def test_layout_knows_who_is_signed_in(make_user):
    ada = make_user("Ada Lovelace")
    html = ada.get("/boards").text
    assert "Sign out" in html and "Create account" not in html


def test_non_members_see_not_found(make_user):
    ada, eve = make_user("Ada Lovelace"), make_user("Eve Moneypenny")
    board_id = _board(ada, "Private")
    page = eve.get(f"/boards/{board_id}").text
    assert "Board not found" in page and "Private" not in page
    assert "Board not found" in eve.get("/boards/not-a-number").text


def test_a_change_from_the_api_reaches_every_open_board(make_user):
    ada, bob = make_user("Ada Lovelace"), make_user("Bob Stone")
    board_id = _board(ada, invite=[bob])
    a, b = ada.tab(f"/boards/{board_id}"), bob.tab(f"/boards/{board_id}")
    try:
        a.wait_for("Bob Stone")  # presence: Bob's tab joined
        ada.api(
            "POST",
            f"/api/boards/{board_id}/tasks",
            json={"title": "Ship it", "assignee_id": bob.actor.id},
        )
        seen_by_bob = b.wait_for("Ship it")
        assert (
            "Ada Lovelace added" in seen_by_bob
        )  # the @effect notice, for others only
        assert "Ship it" in a.wait_for("Ship it")
    finally:
        a.close()
        b.close()


def test_leaving_the_board_updates_presence(make_user):
    ada, bob = make_user("Ada Lovelace"), make_user("Bob Stone")
    board_id = _board(ada, invite=[bob])
    a = ada.tab(f"/boards/{board_id}")
    try:
        b = bob.tab(f"/boards/{board_id}")
        a.wait_for("Here now: Ada Lovelace, Bob Stone<")
        b.close()  # @unmount on Bob's page takes him out of the shared list
        a.wait_for("Here now: Ada Lovelace<")
    finally:
        a.close()


def test_cursor_socket_needs_a_ticket_for_that_board(client, make_user):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    ada, bob = make_user("Ada Lovelace"), make_user("Bob Stone")
    board_id = _board(ada, invite=[bob])
    other = _board(ada, "Other")

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(f"/api/boards/{board_id}/cursors?token=nope"):
            pass
    assert closed.value.code == 1008

    wrong_board = identity.socket_token(ada.actor, other)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/api/boards/{board_id}/cursors?token={wrong_board}"
        ):
            pass

    a_ticket = identity.socket_token(ada.actor, board_id)
    b_ticket = identity.socket_token(bob.actor, board_id)
    with (
        client.websocket_connect(
            f"/api/boards/{board_id}/cursors?token={a_ticket}"
        ) as a,
        client.websocket_connect(
            f"/api/boards/{board_id}/cursors?token={b_ticket}"
        ) as b,
    ):
        a.send_text('{"x": 5, "y": 0}')  # out of range: dropped
        a.send_text('{"x": 0.25, "y": 0.5}')
        assert b.receive_json() == {
            "id": ada.actor.id,
            "name": "Ada Lovelace",
            "x": 0.25,
            "y": 0.5,
        }
