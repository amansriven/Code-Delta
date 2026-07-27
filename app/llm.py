"""LLM-assisted analysis layered on top of reproduced evidence.

Every function here takes findings the engine already reproduced by running
real requests. The LLM explains and extends that evidence — it never decides
on its own whether something is a regression. That distinction is the whole
product (see api-verifier-spec.md), so keep LLM output clearly separated from
the reproduced request/response data in storage and in the UI.

Runs against a local Ollama model (free, no API key) rather than a hosted
API. Ollama's `format: "json"` only guarantees syntactically valid JSON, not
schema conformance the way Claude's structured outputs do, and a local
7-8B model follows instructions far less reliably than a frontier model — so
every response here is validated defensively and any failure just means no
LLM output, never a broken run. Swap back to the Anthropic SDK (see git
history for the prior version of this file) once real API credits exist;
the call sites in engine.py don't need to change either way.
"""

import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "llama3")


def _available() -> bool:
    try:
        httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2.0).raise_for_status()
        return True
    except (httpx.HTTPError, httpx.ConnectError):
        return False


def _generate_json(prompt: str) -> dict | None:
    """Call Ollama with JSON-mode forced; return the parsed object or None.

    None means "no usable output" — caller treats it exactly like the LLM
    being unavailable, since a local model failing to follow instructions is
    just as unusable as the model not running at all.
    """
    try:
        response = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": MODEL, "prompt": prompt, "format": "json", "stream": False},
            timeout=120.0,
        )
        response.raise_for_status()
        return json.loads(response.json()["response"])
    except (httpx.HTTPError, httpx.ConnectError, json.JSONDecodeError, KeyError):
        logger.exception("Ollama call failed or returned unparseable JSON")
        return None


def suggest_extra_cases(
    base_spec: dict, pr_spec: dict, rule_cases: list[dict], limit: int = 5
) -> list[dict]:
    """Propose semantic edge cases the deterministic rules can't derive.

    The rules in openapi_diff.py only know a field's JSON type, so they test
    type/boundary permutations. They can't know that a field named "price"
    should also be tried negative, or that "email" should be tried malformed.
    This fills that gap; it runs after the rules, never instead of them.
    """
    # No rule cases means the OpenAPI diff found nothing to test — there is no
    # changed surface to extend, so skip the call rather than pay for it.
    if not rule_cases or not _available():
        return []

    prompt = (
        "You generate edge-case HTTP requests for API regression testing.\n\n"
        f"Base OpenAPI spec:\n{json.dumps(base_spec)}\n\n"
        f"PR OpenAPI spec:\n{json.dumps(pr_spec)}\n\n"
        "Rule-based cases already generated (do NOT duplicate these):\n"
        f"{json.dumps(rule_cases, indent=2)}\n\n"
        f"Suggest up to {limit} ADDITIONAL requests that exercise semantic edge "
        "cases the type-driven rules above cannot derive — meaning drawn from "
        "field names and descriptions, not just their JSON types. Examples: a "
        "monetary field tried with a negative value, an identifier field tried "
        "with an implausible value, a string field whose name implies a format "
        "tried malformed.\n\n"
        "Only target endpoints and fields present in the specs. Every request "
        "must be one a real client could plausibly send.\n\n"
        "Respond with ONLY a JSON object of this exact shape, no other text:\n"
        '{"cases": [{"name": "...", "method": "...", "path": "...", '
        '"json": {...}, "rationale": "..."}]}'
    )

    result = _generate_json(prompt)
    if not result:
        return []

    cases = []
    for case in result.get("cases", [])[:limit]:
        if not all(k in case for k in ("name", "method", "path", "json")):
            continue  # local model dropped a field — skip rather than guess
        case["source"] = "llm"
        cases.append(case)
    return cases


def explain_findings(findings: list[dict], diff: str | None = None) -> dict[str, dict]:
    """Explain reproduced findings in plain English, keyed by case name.

    `impact` describes what breaks for a real client. `likely_cause` points at
    the change responsible — grounded in the PR diff when one is supplied,
    otherwise inferred from the request/response pair alone and hedged
    accordingly. Returns {} on any failure: this is commentary on evidence that
    already stands on its own, so it must never block or fail a run.
    """
    if not findings or not _available():
        return {}

    diff_section = (
        f"\nThe PR's code diff:\n```diff\n{diff}\n```\n"
        if diff
        else "\nNo code diff is available — infer the cause from the responses "
        "alone and say plainly that you are inferring.\n"
    )

    prompt = (
        "These API behavior changes were reproduced by sending the same request "
        "to both branches of a pull request and recording both real responses. "
        "The evidence is established; your job is to explain it, not re-judge it.\n\n"
        f"Reproduced findings:\n{json.dumps(findings, indent=2)}\n"
        f"{diff_section}\n"
        "For each finding, write:\n"
        "- impact: one sentence on what breaks for a client sending this "
        "request today.\n"
        "- likely_cause: the change most likely responsible. If you're "
        "inferring without a diff, say so rather than guessing confidently.\n\n"
        "Respond with ONLY a JSON object of this exact shape, no other text:\n"
        '{"summaries": [{"case": "...", "impact": "...", "likely_cause": "..."}]}'
    )

    result = _generate_json(prompt)
    if not result:
        return {}

    summaries = {}
    for s in result.get("summaries", []):
        if all(k in s for k in ("case", "impact", "likely_cause")):
            summaries[s["case"]] = {"impact": s["impact"], "likely_cause": s["likely_cause"]}
    return summaries
