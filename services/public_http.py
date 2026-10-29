"""Resolve proxy Fake-IP names without permitting requests to private networks."""
from __future__ import annotations

import http.client
import ipaddress
import json
import socket
from urllib.parse import urlencode
from urllib.request import HTTPHandler, HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener


FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def is_fake_ip(address: str) -> bool:
    return ipaddress.ip_address(address) in FAKE_IP_NETWORK


def is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def resolve_fake_ip(hostname: str) -> tuple[str, ...]:
    """Use TLS-verified, fixed-IP public DNS only for synthetic DNS answers.

    Private answers are never accepted, including those returned by public DNS.
    Proxy discovery is disabled so neither DNS nor destination validation can be
    silently delegated to a proxy. The OS TUN can still carry these connections.
    """
    opener = build_opener(ProxyHandler({}), NoRedirect())
    for endpoint in ("https://1.1.1.1/dns-query", "https://8.8.8.8/resolve"):
        try:
            request = Request(endpoint + "?" + urlencode({"name": hostname, "type": "A"}),
                              headers={"Accept": "application/dns-json"})
            with opener.open(request, timeout=3) as response:
                data = json.loads(response.read(65537))
            if data.get("Status") != 0:
                continue
            addresses = tuple(dict.fromkeys(
                answer["data"] for answer in data.get("Answer", [])
                if answer.get("type") == 1
            ))
            if not addresses:
                continue
            if not all(is_public_ip(address) for address in addresses):
                raise PermissionError("private_network_requests_are_not_allowed")
            return addresses
        except PermissionError:
            raise
        except (OSError, ValueError, KeyError, TypeError):
            continue
    raise ValueError("fake_ip_dns_resolution_failed: 代理返回了 Fake-IP，公网 DNS 解析失败，请检查代理或 DNS 设置")


def pinned_opener(addresses: tuple[str, ...], *handlers):
    """Connect only to validated IPs while preserving HTTP Host and TLS SNI."""
    def connect(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **kwargs):
        last_error = None
        for ip in addresses:
            try:
                return socket.create_connection((ip, address[1]), timeout, source_address)
            except OSError as exc:
                last_error = exc
        raise last_error or OSError("no_public_addresses")

    def factory(connection_type):
        def create(host, **kwargs):
            connection = connection_type(host, **kwargs)
            connection._create_connection = connect
            return connection
        return create

    class PinnedHTTP(HTTPHandler):
        def http_open(self, req):
            return self.do_open(factory(http.client.HTTPConnection), req)

    class PinnedHTTPS(HTTPSHandler):
        def https_open(self, req):
            return self.do_open(factory(http.client.HTTPSConnection), req, context=self._context)

    return build_opener(ProxyHandler({}), PinnedHTTP(), PinnedHTTPS(), *handlers)
