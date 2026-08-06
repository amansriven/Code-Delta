"""Network and parsing policy for untrusted provider source URLs."""

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlparse


class SourcePolicyError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


Resolver = Callable[..., list[tuple]]


def _is_official_host(hostname: str, official_domains: list[str]) -> bool:
    hostname = hostname.lower().rstrip(".")
    return any(
        hostname == domain.lower().rstrip(".")
        or hostname.endswith(f".{domain.lower().rstrip('.')}")
        for domain in official_domains
    )


def validate_source_url(
    url: str,
    official_domains: list[str],
    *,
    resolver: Resolver = socket.getaddrinfo,
) -> None:
    for domain in official_domains:
        normalized = domain.lower().rstrip(".")
        if (
            "." not in normalized
            or any(character in normalized for character in "/*:@")
            or normalized.startswith(".")
        ):
            raise SourcePolicyError(
                "invalid_official_domain", "official domains must be registrable hostnames"
            )
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise SourcePolicyError("scheme_not_allowed", "provider sources must use HTTPS")
    if parsed.username or parsed.password:
        raise SourcePolicyError("credentials_not_allowed", "source URLs cannot contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise SourcePolicyError("port_not_allowed", "source URL contains an invalid port") from exc
    if port not in {None, 443}:
        raise SourcePolicyError("port_not_allowed", "provider sources must use port 443")
    hostname = parsed.hostname
    if not hostname or not _is_official_host(hostname, official_domains):
        raise SourcePolicyError("host_not_allowlisted", "source host is not an official domain")

    try:
        literal = ipaddress.ip_address(hostname)
        addresses = [literal]
    except ValueError:
        try:
            resolved = resolver(hostname, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise SourcePolicyError("dns_failed", "source host could not be resolved") from exc
        addresses = []
        for item in resolved:
            try:
                addresses.append(ipaddress.ip_address(item[4][0]))
            except (IndexError, ValueError):
                continue

    if not addresses:
        raise SourcePolicyError("dns_failed", "source host resolved to no usable addresses")
    if any(not address.is_global for address in addresses):
        raise SourcePolicyError(
            "private_address_blocked",
            "source host resolves to a private, local, reserved, or metadata address",
        )


def enforce_json_depth(value: object, *, maximum: int = 64) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > maximum:
            raise SourcePolicyError("document_too_deep", "source document exceeds nesting limit")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
