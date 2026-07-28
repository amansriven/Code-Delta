from app.openapi_diff import generate_cases, operation_params, shared_endpoints


def test_shared_endpoints_ignore_non_method_path_item_fields():
    spec = {
        "paths": {
            "/items/{item_id}": {
                "parameters": [
                    {
                        "name": "item_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "get": {"responses": {"200": {"description": "OK"}}},
            }
        }
    }

    assert shared_endpoints(spec, spec) == [("/items/{item_id}", "get")]
    cases = generate_cases(spec, spec)
    assert {case["name"] for case in cases} >= {
        "operation_baseline",
        "path_item_id_zero",
        "path_item_id_negative",
    }
    assert all("{" not in case["path"] for case in cases)


def test_operation_parameters_override_inherited_parameters():
    spec = {
        "paths": {
            "/items/{item_id}": {
                "parameters": [
                    {
                        "name": "item_id",
                        "in": "path",
                        "schema": {"type": "string"},
                    }
                ],
                "get": {
                    "parameters": [
                        {
                            "name": "item_id",
                            "in": "path",
                            "schema": {"type": "integer"},
                        }
                    ]
                },
            }
        }
    }

    assert operation_params(spec, "/items/{item_id}", "get")[0]["schema"]["type"] == "integer"


def test_parameter_references_are_resolved():
    spec = {
        "components": {
            "parameters": {
                "Limit": {
                    "name": "limit",
                    "in": "query",
                    "schema": {"type": "integer"},
                }
            }
        },
        "paths": {
            "/items": {
                "get": {
                    "parameters": [{"$ref": "#/components/parameters/Limit"}],
                }
            }
        },
    }

    assert operation_params(spec, "/items", "get")[0]["name"] == "limit"


def test_no_parameter_operation_receives_a_baseline_case():
    spec = {
        "paths": {
            "/health": {
                "get": {
                    "responses": {"200": {"description": "OK"}},
                }
            }
        }
    }

    assert generate_cases(spec, spec) == [
        {
            "id": "get:/health:operation_baseline",
            "name": "operation_baseline",
            "method": "GET",
            "path": "/health",
            "source": "rules",
            "rationale": "Exercise the shared operation with a representative valid request.",
            "json": None,
            "query": {},
        }
    ]


def test_required_body_change_generates_omission_case_with_stable_id():
    base = {
        "components": {
            "schemas": {
                "Item": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "discount": {"type": "number"},
                    },
                    "required": ["name"],
                }
            }
        },
        "paths": {
            "/items": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Item"}}
                        }
                    }
                }
            }
        },
    }
    head = {
        **base,
        "components": {
            "schemas": {
                "Item": {
                    **base["components"]["schemas"]["Item"],
                    "required": ["name", "discount"],
                }
            }
        },
    }

    omission = next(case for case in generate_cases(base, head) if case["name"] == "omit_discount")
    assert omission["id"] == "post:/items:omit_discount"
    assert omission["json"] == {"name": "example"}
