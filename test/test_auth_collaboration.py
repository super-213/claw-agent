from fastapi.testclient import TestClient

from services import ConversationStore, TokenUsageEstimator, UserStore
from services.auth_service import AuthSessionStore
from services.passkeys import PasskeyService
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
    monkeypatch.setattr("web_app.passkeys", PasskeyService(tmp_path / 'passkeys.json'))
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
    admin_ids = [item['id'] for item in client.get('/api/sessions').json()]
    assert admin_session['id'] in admin_ids
    assert alice_session['id'] not in admin_ids
    assert client.get(f"/api/sessions/{alice_session['id']}").status_code == 403
    assert client.patch(f"/api/sessions/{alice_session['id']}/share", json={"scope": "all"}).status_code == 403
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "alice", "password": "secret123"})
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


def test_corrupt_user_store_cannot_reopen_bootstrap(tmp_path):
    import pytest
    path = tmp_path / 'users.json'
    path.write_text('{broken')
    with pytest.raises(RuntimeError, match='user_store_corrupt'):
        UserStore(path).has_admin()


def test_agent_file_read_denies_environment_variants_and_legacy_keys(tmp_path):
    import pytest
    from agent_runtime.builtin_tools import _file_read
    for name in ('.env', '.env.production', '.webui_secret_key', '.webui_secret_key.old'):
        (tmp_path / name).write_text('fixture-secret')
        with pytest.raises(PermissionError, match='protected_credentials'):
            _file_read({'path': name}, (tmp_path,))
    (tmp_path / '.env.example').write_text('PLACEHOLDER=')
    assert _file_read({'path': '.env.example'}, (tmp_path,))['content'] == 'PLACEHOLDER='


def test_new_login_invalidates_the_previous_cookie(tmp_path, monkeypatch):
    client, _, _ = _client_with_auth_state(tmp_path, monkeypatch)
    client.post('/api/auth/bootstrap-admin', json={'username': 'admin', 'password': 'secret123'})
    previous = client.cookies.get(AUTH_COOKIE_NAME)
    client.post('/api/auth/login', json={'username': 'admin', 'password': 'secret123'})
    assert previous != client.cookies.get(AUTH_COOKIE_NAME)
    from web_app import auth_sessions
    assert auth_sessions.get_user_id(previous) is None


def test_self_profile_is_authenticated_scoped_and_persisted(tmp_path, monkeypatch):
    client, users, _ = _client_with_auth_state(tmp_path, monkeypatch)
    assert client.patch('/api/auth/profile', json={'display_name': '称呼'}).status_code == 401
    admin = users.create_user(username='admin', password='secret123', role='admin')
    alice = users.create_user(username='alice', password='secret123')
    client.post('/api/auth/login', json={'username': 'alice', 'password': 'secret123'})
    for extra in ({'role': 'admin'}, {'user_id': admin['id']}, {'username': 'changed'}, {'status': 'disabled'}):
        assert client.patch('/api/auth/profile', json={'display_name': 'Alice', **extra}).status_code == 422
    assert client.patch('/api/auth/profile', json={'display_name': ' '}).status_code == 400
    assert client.patch('/api/auth/profile', json={'display_name': 'x' * 81}).status_code == 422
    result = client.patch('/api/auth/profile', json={'display_name': ' 新称呼 '})
    assert result.status_code == 200
    assert result.json()['user']['display_name'] == '新称呼'
    assert 'password_hash' not in result.json()['user']
    persisted = UserStore(users.path)
    assert persisted.get_user(alice['id'])['display_name'] == '新称呼'
    assert persisted.get_user(alice['id'])['role'] == 'user'
    assert persisted.get_user(admin['id'])['display_name'] == 'admin'
    assert client.get('/api/auth/me').json()['user']['display_name'] == '新称呼'


def test_self_password_change_checks_password_revokes_sessions_and_keeps_passkeys(tmp_path, monkeypatch):
    client, users, _ = _client_with_auth_state(tmp_path, monkeypatch)
    assert client.post('/api/auth/change-password', json={'current_password': 'secret123', 'new_password': 'newpass123'}).status_code == 401
    actor = users.create_user(username='alice', password='secret123', role='admin')
    client.post('/api/auth/login', json={'username': 'alice', 'password': 'secret123', 'remember_me': True})
    token = client.cookies.get(AUTH_COOKIE_NAME)
    from web_app import auth_sessions, passkeys
    other_token = auth_sessions.create(actor['id'])
    with passkeys.store.transaction() as doc:
        doc.setdefault('credentials', {})['fixture-key'] = {'user_id': actor['id']}
    for payload, status in [
        ({'current_password': 'wrong', 'new_password': 'newpass123'}, 400),
        ({'current_password': 'secret123', 'new_password': 'short'}, 422),
        ({'current_password': 'secret123', 'new_password': 'secret123'}, 400),
        ({'current_password': 'secret123', 'new_password': 'newpass123', 'user_id': 'other'}, 422),
    ]:
        assert client.post('/api/auth/change-password', json=payload).status_code == status
        assert users.verify_password('alice', 'secret123')
        assert auth_sessions.get_user_id(token) == actor['id']
    result = client.post('/api/auth/change-password', json={'current_password': 'secret123', 'new_password': 'newpass123'})
    assert result.status_code == 200
    assert 'max-age=0' in result.headers['set-cookie'].lower()
    assert auth_sessions.get_user_id(token) is None
    assert auth_sessions.get_user_id(other_token) is None
    assert client.get('/api/auth/me').status_code == 401
    assert not UserStore(users.path).verify_password('alice', 'secret123')
    assert UserStore(users.path).verify_password('alice', 'newpass123')
    assert 'fixture-key' in passkeys.store.snapshot()['credentials']
    assert client.post('/api/auth/login', json={'username': 'alice', 'password': 'newpass123'}).status_code == 200


def test_account_validation_errors_do_not_echo_credentials(tmp_path, monkeypatch):
    client, users, _ = _client_with_auth_state(tmp_path, monkeypatch)
    users.create_user(username='admin', password='fixture-current', role='admin')
    client.post('/api/auth/login', json={'username': 'admin', 'password': 'fixture-current'})
    cases = [
        ('/api/auth/change-password', {'current_password': 'fixture-current', 'new_password': 'short'}),
        ('/api/auth/change-password', {'current_password': 'fixture-current', 'new_password': 'fixture-new', 'unexpected': 'fixture-secret'}),
        ('/api/auth/change-password', {'current_password': 'fixture-current', 'new_password': {'value': 'fixture-secret'}}),
        ('/api/auth/login', {'username': 'admin', 'password': {'value': 'fixture-secret'}}),
        ('/api/admin/users', {'username': 'new-user', 'password': {'value': 'fixture-secret'}}),
    ]
    for url, payload in cases:
        response = client.post(url, json=payload)
        assert response.status_code == 422
        assert response.json() == {'error': 'invalid_input', 'message': '请检查输入内容后重试。'}
        assert all(secret not in response.text for secret in ['fixture-current', 'fixture-new', 'fixture-secret', 'short'])
    malformed = client.post('/api/auth/change-password', content='{"current_password":"fixture-current","new_password":"fixture-secret",', headers={'Content-Type': 'application/json'})
    assert malformed.status_code == 422
    assert 'fixture-' not in malformed.text
    assert client.get('/api/auth/me').status_code == 200
