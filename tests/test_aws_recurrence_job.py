from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import aws_recurrence_job


def test_build_script_execs_reconcile_inside_running_web_container() -> None:
    script = aws_recurrence_job._build_script(env_name="prod")
    expected_up = (
        'docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d db redis'
    )

    assert 'ENV_FILE=".env.prod"' in script
    assert 'COMPOSE_FILE="docker-compose.prod.yml"' in script
    assert expected_up in script
    # Issue #1422: exec the flask command in the running container (mirrors the
    # #1249 fix for AI insights) — no one-off `run` container, no runtime pip.
    assert "exec -T \\" in script
    assert "web flask recurrence reconcile" in script
    assert "run --rm --no-deps" not in script
    assert "pip install" not in script


def test_wait_raises_ssm_command_failed_with_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_aws(
        ctx: Any, args: list[str], *, expect_json: bool = True
    ) -> dict[str, Any]:
        return {
            "Status": "Failed",
            "StatusDetails": "ExecutionTimedOut",
            "ResponseCode": 1,
            "StandardOutputContent": "recurrence stdout",
            "StandardErrorContent": "recurrence stderr",
        }

    monkeypatch.setattr(aws_recurrence_job, "_run_aws", fake_run_aws)
    ctx = aws_recurrence_job.AwsCtx(profile="", region="us-east-1")

    with pytest.raises(aws_recurrence_job.SsmCommandFailed) as exc_info:
        aws_recurrence_job._wait(ctx, command_id="cmd-123", instance_id="i-prod")

    report = exc_info.value.report
    assert report["command_id"] == "cmd-123"
    assert report["instance_id"] == "i-prod"
    assert report["status"] == "Failed"
    assert "recurrence stderr" in report["stderr_tail"]


def test_write_diagnostics_json_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "report.json"
    payload = {"status": "Success", "command_id": "cmd-123"}

    aws_recurrence_job._write_diagnostics_json(str(target), payload)

    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_run_aws_skips_empty_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(
        cmd: list[str], capture_output: bool, text: bool, check: bool
    ) -> subprocess.CompletedProcess[str]:
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=json.dumps({"ok": True}),
            stderr="",
        )

    monkeypatch.setattr(aws_recurrence_job.subprocess, "run", fake_run)
    ctx = aws_recurrence_job.AwsCtx(profile="", region="us-east-1")

    data = aws_recurrence_job._run_aws(ctx, ["sts", "get-caller-identity"])

    assert data == {"ok": True}
    assert "--profile" not in captured["cmd"]
    assert "--region" in captured["cmd"]
