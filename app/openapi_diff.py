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


def diff_endpoints(base_spec: dict, pr_spec: dict) -> list[tuple[str, str]]:
    """(path, method) pairs present in both specs whose request schema differs."""
    changed = []
    for path, base_methods in base_spec.get("paths", {}).items():
        pr_methods = pr_spec.get("paths", {}).get(path, {})
        for method in base_methods:
            if method not in pr_methods:
                continue
            base_schema = resolve_request_schema(base_spec, path, method)
            pr_schema = resolve_request_schema(pr_spec, path, method)
            if base_schema != pr_schema:
                changed.append((path, method))
    return changed


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


def generate_cases(base_spec: dict, pr_spec: dict) -> list[dict]:
    """Generate edge-case requests for every endpoint/field the OpenAPI diff
    flags as changed in a way that could break existing callers.
    """
    cases = []
    for path, method in diff_endpoints(base_spec, pr_spec):
        base_schema = resolve_request_schema(base_spec, path, method) or {}
        pr_schema = resolve_request_schema(pr_spec, path, method) or {}
        merged_props = {**base_schema.get("properties", {}), **pr_schema.get("properties", {})}

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
