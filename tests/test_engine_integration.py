from app import engine


def test_demo_required_field_regression_is_reproduced(monkeypatch):
    monkeypatch.setattr(engine, "suggest_extra_cases", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "explain_findings", lambda *_args, **_kwargs: {})

    findings = engine.compare(engine.DEMO_DIR / "base", engine.DEMO_DIR / "buggy")

    regression = next(finding for finding in findings if finding["case"] == "omit_discount")
    assert regression["kind"] == "regression"
    assert regression["source"] == "rules"
    assert regression["base_response"]["status_code"] == 201
    assert regression["pr_response"]["status_code"] == 422
