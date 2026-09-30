"""The JSON API: bearer tokens, one service layer, the same rules as the pages."""


def test_api_needs_a_token(client):
    assert client.get("/api/boards").status_code == 401
    bad = client.get("/api/boards", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


def test_board_and_task_lifecycle(make_user):
    ada = make_user("Ada Lovelace")
    board = ada.api(
        "POST",
        "/api/boards",
        json={"basics": {"name": "Launch"}, "team": {"invites": []}},
    )
    assert board.status_code == 201, board.text
    board_id = board.json()["id"]

    task = ada.api(
        "POST", f"/api/boards/{board_id}/tasks", json={"title": "Write post"}
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    assert task.json()["status"] == "todo"

    moved = ada.api("POST", f"/api/tasks/{task_id}/move", json={"status": "done"})
    assert moved.json()["status"] == "done"

    tasks = ada.api("GET", f"/api/boards/{board_id}/tasks").json()
    assert [t["title"] for t in tasks] == ["Write post"]

    assert ada.api("DELETE", f"/api/tasks/{task_id}").status_code == 204
    assert ada.api("GET", f"/api/boards/{board_id}/tasks").json() == []


def test_the_same_validation_as_the_form(make_user):
    ada = make_user("Ada Lovelace")
    board_id = ada.api(
        "POST", "/api/boards", json={"basics": {"name": "B"}, "team": {"invites": []}}
    ).json()["id"]
    empty = ada.api("POST", f"/api/boards/{board_id}/tasks", json={"title": ""})
    assert empty.status_code == 422  # TaskIn: min_length=1


def test_other_peoples_boards_look_missing(make_user):
    ada, eve = make_user("Ada Lovelace"), make_user("Eve Moneypenny")
    board_id = ada.api(
        "POST",
        "/api/boards",
        json={"basics": {"name": "Private"}, "team": {"invites": []}},
    ).json()["id"]
    task_id = ada.api(
        "POST", f"/api/boards/{board_id}/tasks", json={"title": "Secret"}
    ).json()["id"]

    assert eve.api("GET", f"/api/boards/{board_id}/tasks").status_code == 404
    assert (
        eve.api(
            "POST", f"/api/tasks/{task_id}/move", json={"status": "done"}
        ).status_code
        == 404
    )
    assert eve.api("DELETE", f"/api/tasks/{task_id}").status_code == 404
    assert eve.api("GET", "/api/boards").json() == []


def test_assignee_must_be_on_the_board(make_user):
    ada, eve = make_user("Ada Lovelace"), make_user("Eve Moneypenny")
    board_id = ada.api(
        "POST", "/api/boards", json={"basics": {"name": "B"}, "team": {"invites": []}}
    ).json()["id"]
    response = ada.api(
        "POST",
        f"/api/boards/{board_id}/tasks",
        json={"title": "T", "assignee_id": eve.actor.id},
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Pick someone on this board",
        "field": "assignee_id",
    }


def test_invites_need_an_account(make_user):
    ada, bob = make_user("Ada Lovelace"), make_user("Bob Stone")
    missing = ada.api(
        "POST",
        "/api/boards",
        json={
            "basics": {"name": "B"},
            "team": {"invites": [{"email": "nobody@example.com"}]},
        },
    )
    assert missing.status_code == 422
    assert missing.json()["field"] == "team.invites.0.email"

    ok = ada.api(
        "POST",
        "/api/boards",
        json={"basics": {"name": "B"}, "team": {"invites": [{"email": bob.email}]}},
    )
    assert ok.status_code == 201
    assert [b["name"] for b in bob.api("GET", "/api/boards").json()] == ["B"]
