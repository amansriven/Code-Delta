"""OpenAPI-diff-driven edge-case generation (spec Phase 2).

Given two OpenAPI specs, find endpoints whose JSON request body changed in a
way that could break existing callers, then generate edge-case requests
targeted at exactly those fields — instead of a hand-written, fixed list.
"""

DUMMY_BY_TYPE = {
    "string": "example",
    "integer": 1,
    "number": 1.0,
    "boolean": True,
    "array": ["example"],
    "object": {},
}

WRONG_TYPE_BY_TYPE = {
    "string": 12345,
    "integer": "not-a-number",
    "number": "not-a-number",
    "boolean": "not-a-bool",
    "array": "not-a-list",
    "object": "not-an-object",
}

BOUNDARY_BY_TYPE = {
    "string": "",
    "integer": 0,
    "number": 0,
    "array": [],
}

# Path/query params can't be "omitted" the way body fields can (they're baked
# into the URL), so they get their own boundary set instead of reusing
# BOUNDARY_BY_TYPE's single value per type.
PARAM_BOUNDARIES_BY_TYPE = {
    "integer": {"zero": 0, "negative": -1},
    "number": {"zero": 0, "negative": -1},
    "string": {"empty": ""},
}


def _deref(schema: dict, spec: dict) -> dict:
    ref = schema.get("$ref")
    if not ref:
        return schema
    node = spec
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def resolve_request_schema(spec: dict, path: str, method: str) -> dict | None:
    """Resolve the (dereferenced) JSON request-body schema for an operation, if any."""
    op = spec.get("paths", {}).get(path, {}).get(method.lower())
    if not op:
        return None
    schema = (
        op.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema")
    )
    if not schema:
        return None
    return _deref(schema, spec)


def shared_endpoints(base_spec: dict, pr_spec: dict) -> list[tuple[str, str]]:
    """Every (path, method) pair present in both specs.

    Behavioral regressions (e.g. a status code changing) can happen on an
    endpoint whose request schema never changed at all — a bare `GET
    /items/{id}` has no request body to diff, so gating on schema equality
    would skip it entirely. Every shared endpoint gets tested; the body-field
    diff below only controls which *body* edge cases get generated for it.
    """
    endpoints = []
    for path, base_methods in base_spec.get("paths", {}).items():
        pr_methods = pr_spec.get("paths", {}).get(path, {})
        for method in base_methods:
            if method in pr_methods:
                endpoints.append((path, method))
    return endpoints


def operation_params(spec: dict, path: str, method: str) -> list[dict]:
    """All declared parameters (path AND query) for an operation."""
    op = spec.get("paths", {}).get(path, {}).get(method.lower(), {})
    return op.get("parameters", [])


def merged_params(base_spec: dict, pr_spec: dict, path: str, method: str) -> list[dict]:
    """Params from both specs, keyed by (name, location); PR's version wins on
    conflicts (matches _valid_payload's base∪PR merge for body fields) so a
    param that's brand new in the PR still gets tested, not just changed ones.
    """
    base = {(p["name"], p["in"]): p for p in operation_params(base_spec, path, method)}
    pr = {(p["name"], p["in"]): p for p in operation_params(pr_spec, path, method)}
    return list({**base, **pr}.values())


def diff_fields(base_schema: dict, pr_schema: dict) -> list[str]:
    """Fields whose change could break an existing caller: newly required,
    newly added-and-required, or a changed type. Fields that became optional,
    were removed, or are unchanged are not regression-relevant and are skipped.
    """
    base_props = base_schema.get("properties", {})
    pr_props = pr_schema.get("properties", {})
    base_required = set(base_schema.get("required", []))
    pr_required = set(pr_schema.get("required", []))

    changed = []
    for field, pr_field_schema in pr_props.items():
        if field not in base_props and field in pr_required:
            changed.append(field)
        elif field in base_props and field in pr_required and field not in base_required:
            changed.append(field)
        elif field in base_props and base_props[field].get("type") != pr_field_schema.get("type"):
            changed.append(field)
    return changed


def _valid_payload(base_schema: dict, pr_schema: dict) -> dict:
    """A payload with every field (base ∪ PR) filled with a type-appropriate
    dummy value, so it satisfies both schemas' required fields.
    """
    merged_props = {**base_schema.get("properties", {}), **pr_schema.get("properties", {})}
    return {
        field: DUMMY_BY_TYPE.get(schema.get("type"), "example")
        for field, schema in merged_props.items()
    }


def _body_cases(path: str, method: str, base_schema: dict, pr_schema: dict) -> list[dict]:
    merged_props = {**base_schema.get("properties", {}), **pr_schema.get("properties", {})}
    cases = []
    for field in diff_fields(base_schema, pr_schema):
        field_type = merged_props.get(field, {}).get("type")
        base_payload = _valid_payload(base_schema, pr_schema)

        omit_payload = {k: v for k, v in base_payload.items() if k != field}
        cases.append(
            {"name": f"omit_{field}", "method": method.upper(), "path": path, "json": omit_payload}
        )

        if field_type in WRONG_TYPE_BY_TYPE:
            payload = {**base_payload, field: WRONG_TYPE_BY_TYPE[field_type]}
            cases.append(
                {"name": f"wrong_type_{field}", "method": method.upper(), "path": path, "json": payload}
            )

        if field_type in BOUNDARY_BY_TYPE:
            payload = {**base_payload, field: BOUNDARY_BY_TYPE[field_type]}
            cases.append(
                {"name": f"boundary_{field}", "method": method.upper(), "path": path, "json": payload}
            )
    return cases


def _substitute_path(path_template: str, values: dict) -> str:
    result = path_template
    for name, value in values.items():
        result = result.replace("{" + name + "}", str(value))
    return result


def _param_cases(path: str, method: str, params: list[dict]) -> list[dict]:
    """At least one baseline request per endpoint that takes params, plus
    boundary values (zero/negative/empty) per param — this is what actually
    exercises a GET-with-no-body endpoint like `/items/{id}` at all. Query
    params additionally get an omit case (unlike path params, they can be
    left off the URL), since "optional query param became required" is the
    same regression shape as "optional body field became required".
    """
    if not params:
        return []

    path_params = [p for p in params if p.get("in") == "path"]
    query_params = [p for p in params if p.get("in") == "query"]

    def dummy(p: dict):
        return DUMMY_BY_TYPE.get(p.get("schema", {}).get("type"), "example")

    baseline_path = {p["name"]: dummy(p) for p in path_params}
    baseline_query = {p["name"]: dummy(p) for p in query_params}

    def make(name: str, path_values: dict, query_values: dict) -> dict:
        return {
            "name": name,
            "method": method.upper(),
            "path": _substitute_path(path, path_values),
            "query": query_values,
            "json": None,
        }

    cases = [make("param_baseline", baseline_path, baseline_query)]

    for p in path_params:
        param_type = p.get("schema", {}).get("type")
        for boundary_name, boundary_value in PARAM_BOUNDARIES_BY_TYPE.get(param_type, {}).items():
            values = {**baseline_path, p["name"]: boundary_value}
            cases.append(make(f"path_{p['name']}_{boundary_name}", values, baseline_query))

    for p in query_params:
        param_type = p.get("schema", {}).get("type")

        omitted = {k: v for k, v in baseline_query.items() if k != p["name"]}
        cases.append(make(f"omit_query_{p['name']}", baseline_path, omitted))

        for boundary_name, boundary_value in PARAM_BOUNDARIES_BY_TYPE.get(param_type, {}).items():
            values = {**baseline_query, p["name"]: boundary_value}
            cases.append(make(f"query_{p['name']}_{boundary_name}", baseline_path, values))

        if param_type in WRONG_TYPE_BY_TYPE:
            values = {**baseline_query, p["name"]: WRONG_TYPE_BY_TYPE[param_type]}
            cases.append(make(f"wrong_type_query_{p['name']}", baseline_path, values))

    return cases


def generate_cases(base_spec: dict, pr_spec: dict) -> list[dict]:
    """Generate edge-case requests for every endpoint shared by both specs:
    body-field cases for fields the diff flags as changed, plus path/query
    param baseline/boundary/omit cases so endpoints with no body (most GETs)
    still get exercised even when their schema never changed.
    """
    cases = []
    for path, method in shared_endpoints(base_spec, pr_spec):
        base_schema = resolve_request_schema(base_spec, path, method)
        pr_schema = resolve_request_schema(pr_spec, path, method)
        if base_schema != pr_schema:
            cases.extend(_body_cases(path, method, base_schema or {}, pr_schema or {}))

        cases.extend(_param_cases(path, method, merged_params(base_spec, pr_spec, path, method)))
    return cases
