import hashlib
import os
import socket

import httpx
import pytest

from app.ingestion.collector import CollectionError, HTTPSCollector
from app.ingestion.models import ProviderSource
from app.ingestion.security import SourcePolicyError, enforce_json_depth, validate_source_url
from app.ingestion.storage import ArtifactIntegrityError, FilesystemArtifactStore


def public_resolver(host, port, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def private_resolver(host, port, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]


def source(**overrides):
    values = {
        "id": "example-openapi",
        "workspace_id": "workspace-1",
        "provider": {"id": "example", "name": "Example"},
        "source_type": "openapi",
        "canonical_url": "https://api.example.com/openapi.json",
        "official_domains": ["example.com"],
        "adapter_id": "openapi.diff",
    }
    values.update(overrides)
    return ProviderSource.model_validate(values)


@pytest.mark.parametrize(
    ("url", "domains", "code"),
    [
        ("http://api.example.com/spec", ["example.com"], "scheme_not_allowed"),
        ("https://user:pass@api.example.com/spec", ["example.com"], "credentials_not_allowed"),
        ("https://api.example.com:8443/spec", ["example.com"], "port_not_allowed"),
        ("https://example.com.attacker.test/spec", ["example.com"], "host_not_allowlisted"),
        ("https://api.example.com/spec", ["com"], "invalid_official_domain"),
    ],
)
def test_source_policy_rejects_unsafe_urls(url, domains, code):
    with pytest.raises(SourcePolicyError) as error:
        validate_source_url(url, domains, resolver=public_resolver)
    assert error.value.code == code


def test_source_policy_rejects_private_and_metadata_addresses():
    with pytest.raises(SourcePolicyError) as error:
        validate_source_url(
            "https://api.example.com/spec", ["example.com"], resolver=private_resolver
        )
    assert error.value.code == "private_address_blocked"


def test_source_policy_accepts_allowlisted_subdomain_with_public_dns():
    validate_source_url(
        "https://releases.api.example.com/spec",
        ["example.com"],
        resolver=public_resolver,
    )


def test_source_parser_rejects_excessive_nesting():
    document = []
    cursor = document
    for _index in range(10):
        nested = []
        cursor.append(nested)
        cursor = nested

    with pytest.raises(SourcePolicyError) as error:
        enforce_json_depth(document, maximum=5)
    assert error.value.code == "document_too_deep"


def test_filesystem_store_is_content_addressed_and_detects_tampering(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    content = b"official source bytes"
    digest = hashlib.sha256(content).hexdigest()

    object_ref = store.put(content, digest)

    assert store.put(content, digest) == object_ref
    assert store.read(object_ref) == content
    stored_path = store.root / object_ref
    os.chmod(stored_path, 0o640)
    stored_path.write_bytes(b"tampered")
    with pytest.raises(ArtifactIntegrityError, match="integrity"):
        store.read(object_ref)


def test_filesystem_store_rejects_digest_mismatch_and_path_escape(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ArtifactIntegrityError, match="digest"):
        store.put(b"content", "a" * 64)
    with pytest.raises(ArtifactIntegrityError, match="reference"):
        store.read("../secret")


def test_collector_captures_bounded_official_content(tmp_path):
    body = b'{"openapi":"3.1.0","paths":{}}'
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"Content-Type": "application/json", "ETag": '"v1"'},
            content=body,
            request=request,
        )
    )
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    with httpx.Client(transport=transport) as client:
        collector = HTTPSCollector(client, store, resolver=public_resolver)
        artifact = collector.fetch(collector.discover(source())[0])

    assert artifact.sha256 == hashlib.sha256(body).hexdigest()
    assert artifact.etag == '"v1"'
    assert artifact.authoritative is True
    assert store.read(artifact.object_ref) == body


def test_collector_revalidates_and_blocks_redirect_escape(tmp_path):
    def redirect(request):
        return httpx.Response(
            302,
            headers={"Location": "https://attacker.test/payload"},
            request=request,
        )

    store = FilesystemArtifactStore(tmp_path / "artifacts")
    with httpx.Client(transport=httpx.MockTransport(redirect)) as client:
        collector = HTTPSCollector(client, store, resolver=public_resolver)
        with pytest.raises(CollectionError) as error:
            collector.fetch(collector.discover(source())[0])
    assert error.value.code == "host_not_allowlisted"


def test_collector_allows_bounded_redirect_within_official_domains(tmp_path):
    body = b'{"changes":[]}'

    def redirect(request):
        if request.url.host == "api.example.com":
            return httpx.Response(
                302,
                headers={"Location": "https://docs.example.com/openapi.json"},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=body,
            request=request,
        )

    store = FilesystemArtifactStore(tmp_path / "artifacts")
    with httpx.Client(transport=httpx.MockTransport(redirect)) as client:
        collector = HTTPSCollector(client, store, resolver=public_resolver)
        artifact = collector.fetch(collector.discover(source())[0])

    assert str(artifact.retrieved_url) == "https://docs.example.com/openapi.json"
    assert artifact.redirect_count == 1


def test_collector_enforces_redirect_limit(tmp_path):
    def redirect(request):
        step = int(request.url.params.get("step", "0")) + 1
        return httpx.Response(
            302,
            headers={"Location": f"https://api.example.com/openapi.json?step={step}"},
            request=request,
        )

    store = FilesystemArtifactStore(tmp_path / "artifacts")
    with httpx.Client(transport=httpx.MockTransport(redirect)) as client:
        collector = HTTPSCollector(client, store, resolver=public_resolver, max_redirects=2)
        with pytest.raises(CollectionError) as error:
            collector.fetch(collector.discover(source())[0])
    assert error.value.code == "redirect_limit"


def test_collector_uses_cache_validators_and_handles_not_modified(tmp_path):
    observed = {}

    def not_modified(request):
        observed.update(request.headers)
        return httpx.Response(304, headers={"ETag": '"v1"'}, request=request)

    store = FilesystemArtifactStore(tmp_path / "artifacts")
    with httpx.Client(transport=httpx.MockTransport(not_modified)) as client:
        collector = HTTPSCollector(client, store, resolver=public_resolver)
        descriptor = collector.discover(
            source(), etag='"v1"', last_modified="Wed, 05 Aug 2026 12:00:00 GMT"
        )[0]
        artifact = collector.fetch(descriptor)

    assert observed["if-none-match"] == '"v1"'
    assert "if-modified-since" in observed
    assert artifact.retrieval_status == "not_modified"


def test_collector_enforces_decompression_ratio(tmp_path):
    body = b"{" + b" " * 100 + b"}"

    def compressed(request):
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json", "Content-Length": "1"},
            content=body,
            request=request,
        )

    store = FilesystemArtifactStore(tmp_path / "artifacts")
    with httpx.Client(transport=httpx.MockTransport(compressed)) as client:
        collector = HTTPSCollector(
            client, store, resolver=public_resolver, max_decompression_ratio=10
        )
        with pytest.raises(CollectionError) as error:
            collector.fetch(collector.discover(source())[0])
    assert error.value.code == "decompression_limit"


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            {"headers": {"Content-Type": "text/html"}, "content": b"<html></html>"},
            "media_type_blocked",
        ),
        (
            {"headers": {"Content-Type": "application/json"}, "content": b"12345"},
            "artifact_too_large",
        ),
    ],
)
def test_collector_rejects_disallowed_or_oversized_content(tmp_path, response, code):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, request=request, **response)
    )
    configured = source(max_artifact_bytes=4)
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    with httpx.Client(transport=transport) as client:
        collector = HTTPSCollector(client, store, resolver=public_resolver)
        with pytest.raises(CollectionError) as error:
            collector.fetch(collector.discover(configured)[0])
    assert error.value.code == code
