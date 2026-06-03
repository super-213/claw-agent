from fastapi.testclient import TestClient

from services import ConversationStore, TokenUsageEstimator, UserStore
from services.auth_service import AuthSessionStore
from web_app import AUTH_COOKIE_NAME, app


def _client_with_auth_state(tmp_path, monkeypatch, auth_session_store=None):
    user_store = UserStore(tmp_path / "users.json")
    conversation_store = ConversationStore(
        tmp_path / "conversations",
        token_estimator=TokenUsageEstimator(),
    )
    monkeypatch.setattr("web_app.user_store", user_store)
    monkeypatch.setattr("web_app.store", conversation_store)
    monkeypatch.setattr("web_app.auth_sessions", auth_session_store or AuthSessionStore())
    app.config["TESTING"] = False
    return TestClient(app), user_store, conversation_store


def test_requires_login_for_session_api(tmp_path, monkeypatch):
    client, _users, _store = _client_with_auth_state(tmp_path, monkeypatch)

    response = client.get("/api/sessions")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_bootstrap_admin_only_once_and_no_public_register(tmp_path, monkeypatch):
    client, users, store = _client_with_auth_state(tmp_path, monkeypatch)
    legacy = store.create_session("system")

    response = client.post(
        "/api/auth/bootstrap-admin",
        json={"username": "admin", "password": "secret123"},
    )

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"
    assert users.has_admin()
    assert store.load_session(legacy["id"])["owner_user_id"] == response.json()["user"]["id"]

    second = client.post(
        "/api/auth/bootstrap-admin",
        json={"username": "root", "password": "secret123"},
    )
    assert second.status_code == 409
    assert client.post("/api/auth/register", json={}).status_code in {404, 405}


def test_admin_crud_user_and_regular_user_login(tmp_path, monkeypatch):
    client, _users, _store = _client_with_auth_state(tmp_path, monkeypatch)
    client.post("/api/auth/bootstrap-admin", json={"username": "admin", "password": "secret123"})

    created = client.post(
        "/api/admin/users",
        json={"username": "alice", "password": "secret123", "display_name": "Alice"},
    )

    assert created.status_code == 201
    user_id = created.json()["user"]["id"]
    assert client.patch(f"/api/admin/users/{user_id}", json={"display_name": "Alice A"}).status_code == 200
    assert client.post(f"/api/admin/users/{user_id}/reset-password", json={"password": "newpass123"}).status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.post("/api/auth/login", json={"username": "alice", "password": "newpass123"}).status_code == 200
    assert client.get("/api/admin/users").status_code == 403


def test_login_without_remember_me_uses_session_cookie(tmp_path, monkeypatch):
    client, _users, _store = _client_with_auth_state(tmp_path, monkeypatch)
    client.post("/api/auth/bootstrap-admin", json={"username": "admin", "password": "secret123"})
    client.post("/api/auth/logout")

    response = client.post("/api/auth/login", json={"username": "admin", "password": "secret123"})

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "").lower()
    assert AUTH_COOKIE_NAME in set_cookie
    assert "max-age" not in set_cookie

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert "max-age" not in me.headers.get("set-cookie", "").lower()


def test_remember_me_cookie_survives_session_store_restart(tmp_path, monkeypatch):
    auth_path = tmp_path / "auth_sessions.json"
    client, _users, _store = _client_with_auth_state(
        tmp_path,
        monkeypatch,
        AuthSessionStore(path=auth_path),
    )
    client.post("/api/auth/bootstrap-admin", json={"username": "admin", "password": "secret123"})
    client.post("/api/auth/logout")

    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret123", "remember_me": True},
    )

    token = response.cookies.get(AUTH_COOKIE_NAME)
    set_cookie = response.headers.get("set-cookie", "").lower()
    assert response.status_code == 200
    assert token
    assert "max-age=2592000" in set_cookie

    monkeypatch.setattr("web_app.auth_sessions", AuthSessionStore(path=auth_path))
    restarted_client = TestClient(app)
    restarted_client.cookies.set(AUTH_COOKIE_NAME, token)

    me = restarted_client.get("/api/auth/me")

    assert me.status_code == 200
    assert me.json()["user"]["username"] == "admin"
    assert "max-age=2592000" in me.headers.get("set-cookie", "").lower()


def test_session_visibility_and_selected_share(tmp_path, monkeypatch):
    client, _users, _store = _client_with_auth_state(tmp_path, monkeypatch)
    admin = client.post("/api/auth/bootstrap-admin", json={"username": "admin", "password": "secret123"}).json()["user"]
    alice = client.post("/api/admin/users", json={"username": "alice", "password": "secret123"}).json()["user"]
    bob = client.post("/api/admin/users", json={"username": "bob", "password": "secret123"}).json()["user"]

    admin_session = client.post("/api/sessions").json()
    assert admin_session["owner_user_id"] == admin["id"]

    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username": "alice", "password": "secret123"}).status_code == 200
    alice_session = client.post("/api/sessions").json()
    listed = client.get("/api/sessions").json()
    assert [session["id"] for session in listed] == [alice_session["id"]]

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "admin", "password": "secret123"})
    share_response = client.patch(
        f"/api/sessions/{alice_session['id']}/share",
        json={"scope": "selected", "user_ids": [bob["id"]], "permission": "write"},
    )
    assert share_response.status_code == 200

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "bob", "password": "secret123"})
    bob_ids = [session["id"] for session in client.get("/api/sessions").json()]
    assert alice_session["id"] in bob_ids
    assert admin_session["id"] not in bob_ids
    assert client.delete(f"/api/sessions/{alice_session['id']}").status_code == 403
