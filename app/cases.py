"""Shared types and identity helpers for generated executable requests."""

from typing import NotRequired, TypedDict


class RequestCase(TypedDict):
    """A request candidate that can be executed against both app versions."""

    id: str
    name: str
    method: str
    path: str
    source: str
    rationale: str
    json: NotRequired[object]
    query: NotRequired[dict[str, object]]


def case_id(method: str, path: str, name: str) -> str:
    """Return a stable operation-scoped identifier for a generated case."""
    return f"{method.lower()}:{path}:{name}"


def make_case(
    *,
    name: str,
    method: str,
    path: str,
    rationale: str,
    json: object | None = None,
    query: dict[str, object] | None = None,
    source: str = "rules",
) -> RequestCase:
    normalized_method = method.upper()
    return {
        "id": case_id(normalized_method, path, name),
        "name": name,
        "method": normalized_method,
        "path": path,
        "source": source,
        "rationale": rationale,
        "json": json,
        "query": query or {},
    }
