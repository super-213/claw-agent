import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent_runtime import builtin_tools as tools
from services import public_http


def dns(monkeypatch, *addresses):
    monkeypatch.setattr(tools.socket, "getaddrinfo", lambda *args: [
        (2, 1, 6, "", (address, 0)) for address in addresses
    ])


@pytest.mark.parametrize("host,address", [
    ("localhost", "127.0.0.1"), ("private.example", "192.168.1.2"),
    ("private.example", "169.254.169.254"), ("private.example", "::1"),
    ("198.18.0.1", "198.18.0.1"), ("private.example", "100.64.0.1"),
])
def test_private_and_literal_fake_ips_never_use_fallback(monkeypatch, host, address):
    dns(monkeypatch, address)
    fallback = Mock()
    monkeypatch.setattr(tools, "resolve_fake_ip", fallback)
    with pytest.raises(PermissionError, match="private_network"):
        tools._reject_private_host(host)
    fallback.assert_not_called()


def test_synthetic_dns_uses_validated_public_resolution(monkeypatch):
    dns(monkeypatch, "198.18.0.214")
    fallback = Mock(return_value=("198.35.26.224",))
    monkeypatch.setattr(tools, "resolve_fake_ip", fallback)
    assert tools._reject_private_host("zh.wikipedia.org") == ("198.35.26.224",)
    fallback.assert_called_once_with("zh.wikipedia.org")


def test_mixed_public_and_private_answers_are_denied(monkeypatch):
    dns(monkeypatch, "198.35.26.224", "127.0.0.1")
    with pytest.raises(PermissionError):
        tools._reject_private_host("mixed.example")


def test_doh_rejects_private_answers_and_disables_proxies(monkeypatch):
    response = BytesIO(json.dumps({"Status": 0, "Answer": [{"type": 1, "data": "127.0.0.1"}]}).encode())
    opener = Mock()
    opener.open.return_value = response
    build = Mock(return_value=opener)
    monkeypatch.setattr(public_http, "build_opener", build)
    with pytest.raises(PermissionError):
        public_http.resolve_fake_ip("unsafe.example")
    assert build.call_args.args[0].proxies == {}


def test_doh_fails_closed_when_resolvers_unavailable(monkeypatch):
    opener = Mock()
    opener.open.side_effect = OSError("offline")
    monkeypatch.setattr(public_http, "build_opener", Mock(return_value=opener))
    with pytest.raises(ValueError, match="fake_ip_dns_resolution_failed"):
        public_http.resolve_fake_ip("example.com")
    assert opener.open.call_count == 2


def test_pinned_https_preserves_hostname_and_never_reresolves_destination(monkeypatch):
    # Inspect the connection passed to urllib; HTTPConnection.connect uses this
    # connector, while HTTPSConnection retains its original host for TLS SNI.
    connect = Mock(return_value=object())
    monkeypatch.setattr(public_http.socket, "create_connection", connect)
    monkeypatch.setattr(public_http, "build_opener", lambda *handlers: handlers)
    handlers = public_http.pinned_opener(("198.35.26.224",))
    handler = next(h for h in handlers if isinstance(h, public_http.HTTPSHandler))
    def do_open(factory, req, **kwargs):
        connection = factory("zh.wikipedia.org", timeout=3, **kwargs)
        assert connection.host == "zh.wikipedia.org"
        connection._create_connection((connection.host, 443), 3)
    handler.do_open = do_open
    handler.https_open(object())
    connect.assert_called_once_with(("198.35.26.224", 443), 3, None)


def test_fake_ip_requests_use_pinned_transport_and_encode_unicode(monkeypatch):
    dns(monkeypatch, "198.18.0.214")
    monkeypatch.setattr(tools, "resolve_fake_ip", lambda host: ("198.35.26.224",))
    response = BytesIO(b"page")
    response.headers = SimpleNamespace(get=lambda *args: "text/html", get_content_charset=lambda: "utf-8")
    response.status = 200
    response.geturl = lambda: "https://zh.wikipedia.org/wiki/test"
    opener = Mock()
    opener.open.return_value = response
    pin = Mock(return_value=opener)
    monkeypatch.setattr(tools, "pinned_opener", pin)
    assert tools._http_request({"url": "https://zh.wikipedia.org/wiki/坂本日常"})["body"] == "page"
    assert pin.call_args.args[0] == ("198.35.26.224",)
    assert "%E5%9D%82" in opener.open.call_args.args[0].full_url


def test_web_file_aliases_stay_inside_generated_root(tmp_path):
    generated = tmp_path / "files"
    generated.mkdir()
    (generated / "notes.txt").write_text("uploaded text")
    (tmp_path / "secret.txt").write_text("secret")
    roots = (tmp_path, generated)
    assert tools._file_read({"path": "/generated/notes.txt"}, roots)["content"] == "uploaded text"
    with pytest.raises(PermissionError):
        tools._file_read({"path": "/generated/%2e%2e/secret.txt"}, roots)
    (generated / "image.jpg").write_bytes(b"binary")
    with pytest.raises(ValueError, match="image_requires_visual_input"):
        tools._file_read({"path": "/generated/image.jpg"}, roots)
