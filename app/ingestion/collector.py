"""Bounded HTTPS collector for configured official provider sources."""

import hashlib
import socket
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx

from app.ingestion.models import ArtifactDescriptor, CapturedArtifact, ProviderSource
from app.ingestion.security import SourcePolicyError, validate_source_url
from app.ingestion.storage import ArtifactStore


class CollectionError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


ACCEPTED_MEDIA_TYPES = {
    "openapi": ["application/json"],
    "structured_release": ["application/json"],
    "changelog": ["text/html", "text/markdown", "text/plain"],
    "migration_guide": ["text/html", "text/markdown", "text/plain", "application/pdf"],
    "sdk_release": ["application/json", "text/html", "text/markdown", "text/plain"],
}


class HTTPSCollector:
    collector_id = "https-official-source"
    collector_version = "1.0.0"

    def __init__(
        self,
        client: httpx.Client,
        artifact_store: ArtifactStore,
        *,
        resolver: Callable[..., list[tuple]] = socket.getaddrinfo,
        max_redirects: int = 3,
        max_decompression_ratio: int = 20,
    ):
        self.client = client
        self.artifact_store = artifact_store
        self.resolver = resolver
        self.max_redirects = max_redirects
        self.max_decompression_ratio = max_decompression_ratio

    def discover(
        self,
        source: ProviderSource,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> list[ArtifactDescriptor]:
        return [
            ArtifactDescriptor(
                source_id=source.id,
                canonical_url=source.canonical_url,
                official_domains=source.official_domains,
                max_artifact_bytes=source.max_artifact_bytes,
                accepted_media_types=ACCEPTED_MEDIA_TYPES[source.source_type],
                etag=etag,
                last_modified=last_modified,
            )
        ]

    def fetch(self, descriptor: ArtifactDescriptor) -> CapturedArtifact:
        url = str(descriptor.canonical_url)
        headers = {"Accept": ", ".join(descriptor.accepted_media_types)}
        if descriptor.etag:
            headers["If-None-Match"] = descriptor.etag
        if descriptor.last_modified:
            headers["If-Modified-Since"] = descriptor.last_modified

        redirects = 0
        while True:
            try:
                validate_source_url(url, descriptor.official_domains, resolver=self.resolver)
            except SourcePolicyError as exc:
                raise CollectionError(exc.code, str(exc)) from exc
            request = self.client.build_request("GET", url, headers=headers)
            try:
                response = self.client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise CollectionError("request_failed", "official source request failed") from exc
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise CollectionError("invalid_redirect", "redirect omitted Location")
                    redirects += 1
                    if redirects > self.max_redirects:
                        raise CollectionError("redirect_limit", "source exceeded redirect limit")
                    url = urljoin(url, location)
                    continue
                if response.status_code == 304:
                    return CapturedArtifact(
                        id=f"artifact:{descriptor.source_id}:not-modified",
                        source_id=descriptor.source_id,
                        canonical_url=descriptor.canonical_url,
                        retrieved_url=url,
                        captured_at=datetime.now(UTC),
                        retrieval_status="not_modified",
                        media_type="application/octet-stream",
                        size_bytes=0,
                        sha256="0" * 64,
                        object_ref="not-modified",
                        collector_id=self.collector_id,
                        collector_version=self.collector_version,
                        etag=response.headers.get("etag") or descriptor.etag,
                        last_modified=response.headers.get("last-modified")
                        or descriptor.last_modified,
                        redirect_count=redirects,
                    )
                if not 200 <= response.status_code < 300:
                    raise CollectionError(
                        "http_error", f"official source returned HTTP {response.status_code}"
                    )
                media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if media_type not in descriptor.accepted_media_types:
                    raise CollectionError("media_type_blocked", "source media type is not allowed")
                declared_length = response.headers.get("content-length")
                try:
                    declared_bytes = int(declared_length) if declared_length else None
                except ValueError as exc:
                    raise CollectionError(
                        "invalid_content_length", "source returned an invalid content length"
                    ) from exc
                if declared_bytes is not None and declared_bytes < 0:
                    raise CollectionError(
                        "invalid_content_length", "source returned an invalid content length"
                    )
                if declared_bytes is not None and declared_bytes > descriptor.max_artifact_bytes:
                    raise CollectionError(
                        "artifact_too_large", "source artifact exceeds size limit"
                    )
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > descriptor.max_artifact_bytes:
                        raise CollectionError(
                            "artifact_too_large", "source artifact exceeds size limit"
                        )
                if declared_bytes is not None and declared_bytes > 0:
                    ratio = len(content) / declared_bytes
                    if ratio > self.max_decompression_ratio:
                        raise CollectionError(
                            "decompression_limit", "source artifact exceeds decompression ratio"
                        )
            finally:
                response.close()

            body = bytes(content)
            digest = hashlib.sha256(body).hexdigest()
            object_ref = self.artifact_store.put(body, digest)
            return CapturedArtifact(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{descriptor.source_id}:{digest}")),
                source_id=descriptor.source_id,
                canonical_url=descriptor.canonical_url,
                retrieved_url=url,
                captured_at=datetime.now(UTC),
                retrieval_status="captured",
                media_type=media_type,
                size_bytes=len(body),
                sha256=digest,
                object_ref=object_ref,
                collector_id=self.collector_id,
                collector_version=self.collector_version,
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
                redirect_count=redirects,
            )
