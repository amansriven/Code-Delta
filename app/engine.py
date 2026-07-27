import socket
import subprocess
import time
from pathlib import Path

import httpx

from app.llm import explain_findings, suggest_extra_cases
from app.openapi_diff import generate_cases

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo_apps"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RunningApp:
    def __init__(self, app_dir: Path):
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.process = subprocess.Popen(
            ["uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=app_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def wait_ready(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"app at {self.base_url} exited before becoming ready")
            try:
                httpx.get(f"{self.base_url}/openapi.json", timeout=1.0).raise_for_status()
                return
            except (httpx.HTTPError, httpx.ConnectError):
                time.sleep(0.2)
        raise RuntimeError(f"app at {self.base_url} did not become ready in time")

    def stop(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()


def _run_case(base_url: str, case: dict) -> dict:
    with httpx.Client() as client:
        resp = client.request(
            case["method"],
            f"{base_url}{case['path']}",
            json=case.get("json"),
            params=case.get("query"),
        )
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    return {"status_code": resp.status_code, "body": body}


def compare(base_dir: Path, pr_dir: Path, diff: str | None = None) -> list[dict]:
    """Diff both apps' OpenAPI specs to find changed endpoints/fields, generate
    edge-case requests targeted at those changes, run them against both apps,
    and return findings where behavior differed between base and PR:

    - "regression": base succeeded (2xx), PR failed — the spec's core case
    - "status_code_changed": the status code differs some other way (e.g. a
      404 silently becoming a 200) — still worth surfacing even though it
      isn't a pass-to-fail flip, per the spec's own "404 -> 200" example

    Requests where both branches return the same status code (both pass, or
    both fail identically) are dropped — nothing changed, or it's pre-existing
    and not this PR's fault.
    """
    base_app = RunningApp(base_dir)
    pr_app = RunningApp(pr_dir)
    try:
        base_app.wait_ready()
        pr_app.wait_ready()

        base_spec = httpx.get(f"{base_app.base_url}/openapi.json").json()
        pr_spec = httpx.get(f"{pr_app.base_url}/openapi.json").json()
        cases = generate_cases(base_spec, pr_spec)
        cases += suggest_extra_cases(base_spec, pr_spec, cases)

        findings = []
        for case in cases:
            base_result = _run_case(base_app.base_url, case)
            pr_result = _run_case(pr_app.base_url, case)
            base_ok = 200 <= base_result["status_code"] < 300
            pr_ok = 200 <= pr_result["status_code"] < 300

            if base_ok and not pr_ok:
                kind = "regression"
            elif base_result["status_code"] != pr_result["status_code"]:
                kind = "status_code_changed"
            else:
                continue

            findings.append(
                {
                    "kind": kind,
                    "case": case["name"],
                    "source": case.get("source", "rules"),
                    "request": {
                        "method": case["method"],
                        "path": case["path"],
                        "json": case.get("json"),
                    },
                    "base_response": base_result,
                    "pr_response": pr_result,
                }
            )

        # Explanations are commentary on evidence that already stands alone —
        # attached under a separate key so the UI can't blur the two.
        for case_name, explanation in explain_findings(findings, diff).items():
            for finding in findings:
                if finding["case"] == case_name:
                    finding["explanation"] = explanation

        return findings
    finally:
        base_app.stop()
        pr_app.stop()


if __name__ == "__main__":
    import json

    print(json.dumps(compare(DEMO_DIR / "base", DEMO_DIR / "buggy"), indent=2))
