from app.engine import classify_response_change


def response(status_code: int, body=None) -> dict:
    return {"status_code": status_code, "body": body}


def test_success_to_failure_is_a_regression():
    assert classify_response_change(response(201), response(422)) == "regression"


def test_other_status_change_is_behavior_change():
    assert classify_response_change(response(404), response(200)) == "status_code_changed"


def test_matching_status_is_currently_suppressed():
    assert (
        classify_response_change(response(200, {"value": 1}), response(200, {"value": 2})) is None
    )
