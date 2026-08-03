"""Guards for the contract snapshot gate (#1536).

The gate only protects the go-live freeze if it actually runs on every pull
request. These tests fail if someone removes the job, stops calling the script,
or narrows the workflow with a ``paths`` filter — which is exactly how the two
pre-existing contract workflows ended up blind:

- ``openapi-diff.yml`` runs only when ``openapi.json`` itself changes;
- ``postman-sync.yml`` runs only on push to master.

Neither catches a controller change merged with a stale snapshot.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CONTRACTS_SCRIPT = REPO_ROOT / "scripts" / "check_contracts.sh"


def _load_ci_workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # ``on`` is parsed as the boolean True by the YAML 1.1 loader.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict), "ci.yml must declare trigger mapping"
    return triggers


def test_contracts_job_exists_and_runs_the_script() -> None:
    jobs = _load_ci_workflow()["jobs"]
    assert "contracts" in jobs, "ci.yml lost the contract snapshot gate (#1536)"

    steps = jobs["contracts"]["steps"]
    commands = " ".join(str(step.get("run", "")) for step in steps)
    assert "scripts/check_contracts.sh" in commands


def test_contracts_gate_runs_on_every_pull_request() -> None:
    """No ``paths`` filter — a stale snapshot must never slip through."""
    triggers = _triggers(_load_ci_workflow())

    assert "pull_request" in triggers
    pull_request = triggers["pull_request"] or {}
    assert isinstance(pull_request, dict)
    assert "paths" not in pull_request
    assert "paths-ignore" not in pull_request


def test_contracts_job_has_no_conditional_skip() -> None:
    contracts_job = _load_ci_workflow()["jobs"]["contracts"]
    assert "if" not in contracts_job
    assert "needs" not in contracts_job


def test_script_checks_both_snapshots() -> None:
    assert CONTRACTS_SCRIPT.exists()
    assert os.access(CONTRACTS_SCRIPT, os.X_OK), "check_contracts.sh must be executable"

    body = CONTRACTS_SCRIPT.read_text(encoding="utf-8")
    assert "check-openapi-drift.sh" in body
    assert "export_graphql_docs.py" in body


def test_package_json_exposes_contracts_check() -> None:
    package_json = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    assert package_json["scripts"]["contracts:check"] == (
        "bash scripts/check_contracts.sh"
    )


def test_local_ci_mirror_runs_the_gate() -> None:
    """`run_ci_quality_local.sh` claims to mirror ci.yml — keep it honest."""
    mirror = (REPO_ROOT / "scripts" / "run_ci_quality_local.sh").read_text(
        encoding="utf-8"
    )
    assert mirror.count("scripts/check_contracts.sh") >= 2, (
        "both the docker and --local modes must run the contract gate"
    )
