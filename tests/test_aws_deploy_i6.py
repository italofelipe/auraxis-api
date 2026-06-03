from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import aws_deploy_i6

# ---------------------------------------------------------------------------
# GHCR URI validator (#1253)
# ---------------------------------------------------------------------------


def test_is_valid_ghcr_image_uri_accepts_canonical_ghcr_form() -> None:
    assert (
        aws_deploy_i6.is_valid_ghcr_image_uri("ghcr.io/italofelipe/auraxis-api:abc123")
        is True
    )


def test_is_valid_ghcr_image_uri_accepts_full_sha_tag() -> None:
    sha = "3d8274a495d97980753586a0fb80f71e595a7a9d"
    assert (
        aws_deploy_i6.is_valid_ghcr_image_uri(f"ghcr.io/italofelipe/auraxis-api:{sha}")
        is True
    )


def test_is_valid_ghcr_image_uri_rejects_bare_git_sha() -> None:
    bare_sha = "347450dd08db94595e192dfb90a0e194ab9fa890"
    assert aws_deploy_i6.is_valid_ghcr_image_uri(bare_sha) is False


def test_is_valid_ghcr_image_uri_rejects_dockerhub_form() -> None:
    assert aws_deploy_i6.is_valid_ghcr_image_uri("library/auraxis-api:latest") is False


def test_is_valid_ghcr_image_uri_rejects_missing_tag() -> None:
    assert (
        aws_deploy_i6.is_valid_ghcr_image_uri("ghcr.io/italofelipe/auraxis-api")
        is False
    )


def test_is_valid_ghcr_image_uri_rejects_empty_string() -> None:
    assert aws_deploy_i6.is_valid_ghcr_image_uri("") is False


def test_is_valid_ghcr_image_uri_rejects_whitespace_only() -> None:
    assert aws_deploy_i6.is_valid_ghcr_image_uri("   ") is False


def test_is_valid_ghcr_image_uri_rejects_none_like_inputs() -> None:
    assert aws_deploy_i6.is_valid_ghcr_image_uri(None) is False  # type: ignore[arg-type]
    assert aws_deploy_i6.is_valid_ghcr_image_uri(123) is False  # type: ignore[arg-type]


def test_ghcr_image_uri_pattern_matches_bash_regex() -> None:
    """The Python validator and the bash regex must agree on the same shape.

    The deploy script embeds an extended-regex (ERE) variant of this pattern
    inside the SSM bash heredoc for in-container validation. If they diverge,
    operators get inconsistent behavior between dry-run and live-run paths.
    """
    pattern = aws_deploy_i6.GHCR_IMAGE_URI_PATTERN
    assert pattern.startswith("^ghcr\\.io/")
    # The pattern must require a tag (":<something>").
    assert ":" in pattern
    compiled = re.compile(pattern)
    assert compiled.match("ghcr.io/italofelipe/auraxis-api:v1") is not None
    assert compiled.match("347450dd08db94595e192dfb90a0e194ab9fa890") is None


# ---------------------------------------------------------------------------
# Rollback bash-template assertions (#1253)
# ---------------------------------------------------------------------------


def test_build_script_rollback_validates_state_previous_against_ghcr_regex() -> None:
    script = aws_deploy_i6._build_script(
        env_name="prod",
        aws_region="us-east-1",
        git_ref=None,
        mode="rollback",
    )
    # The rollback branch must guard STATE_PREVIOUS with the canonical pattern
    # before assigning it to WEB_IMAGE.
    assert 'if [ "$MODE" = "rollback" ]; then' in script
    assert "ghcr\\.io/" in script
    # The error message must mention the state file path so operators can
    # locate and repair it.
    assert aws_deploy_i6.DEPLOY_STATE_PATH in script
    assert "not a valid GHCR image URI" in script
    # Must use a distinct exit code from "no previous deploy recorded" (12).
    assert "exit 14" in script


def test_build_script_rollback_preserves_empty_state_previous_path() -> None:
    """Empty STATE_PREVIOUS must still hit the original 'no previous deploy
    recorded' branch (exit 12), not the new invalid-URI branch (exit 14).
    """
    script = aws_deploy_i6._build_script(
        env_name="prod",
        aws_region="us-east-1",
        git_ref=None,
        mode="rollback",
    )
    # Empty-string guard appears before the format validation guard.
    empty_guard_idx = script.find('if [ -z "$STATE_PREVIOUS" ]; then')
    format_guard_idx = script.find("not a valid GHCR image URI")
    assert empty_guard_idx != -1, "expected empty-state guard"
    assert format_guard_idx != -1, "expected format-validation guard"
    assert empty_guard_idx < format_guard_idx, (
        "empty-state guard must run before format-validation guard so empty "
        "STATE_PREVIOUS exits 12, not 14"
    )


# ---------------------------------------------------------------------------
# Deploy-state schema versioning (#1253)
# ---------------------------------------------------------------------------


def test_deploy_state_schema_version_constant_is_defined() -> None:
    assert isinstance(aws_deploy_i6.DEPLOY_STATE_SCHEMA_VERSION, int)
    assert aws_deploy_i6.DEPLOY_STATE_SCHEMA_VERSION >= 2


def test_build_script_writes_schema_version_to_deploy_state() -> None:
    script = aws_deploy_i6._build_script(
        env_name="prod",
        aws_region="us-east-1",
        git_ref="origin/master",
        mode="deploy",
    )
    # The script must persist the schema_version so future state migrations
    # can detect this format.
    assert "schema_version" in script
    assert f"{aws_deploy_i6.DEPLOY_STATE_SCHEMA_VERSION}" in script


# ---------------------------------------------------------------------------
# Migration step on deploy (#1252)
# ---------------------------------------------------------------------------


def test_build_script_deploy_runs_flask_db_upgrade_before_healthz_validation() -> None:
    script = aws_deploy_i6._build_script(
        env_name="prod",
        aws_region="us-east-1",
        git_ref="origin/master",
        mode="deploy",
    )

    # Must invoke 'flask db upgrade' inside the running web container.
    assert "flask db upgrade" in script

    # Position check: the migration step must appear AFTER 'compose ... up -d'
    # for the web container, and BEFORE the /healthz curl validation loop.
    upgrade_idx = script.find("flask db upgrade")
    healthz_idx = script.find("validating healthz")
    web_up_idx = script.find("swapping web container")

    assert web_up_idx != -1, "expected web container swap section"
    assert upgrade_idx != -1, "expected flask db upgrade invocation"
    assert healthz_idx != -1, "expected /healthz validation section"
    assert web_up_idx < upgrade_idx < healthz_idx, (
        "flask db upgrade must run after the web container is up and "
        "before the /healthz validation loop"
    )


def test_build_script_aborts_when_alembic_upgrade_fails() -> None:
    script = aws_deploy_i6._build_script(
        env_name="prod",
        aws_region="us-east-1",
        git_ref="origin/master",
        mode="deploy",
    )
    # The script must abort with a distinct exit code if the alembic upgrade
    # exits non-zero. We use exit 36 (next free slot after the existing
    # 30-35 deploy-stage exits).
    assert "exit 36" in script
    # Must surface the alembic stderr in the log so on-call has a starting
    # point — the existing dump_compose_diagnostics helper covers this.
    assert "alembic upgrade failed" in script


def test_build_script_prints_alembic_stderr_last_for_ssm_tail_visibility() -> None:
    """#1429: the real alembic error must print AFTER dump_compose_diagnostics.

    SSM caps command output (~24KB, keeps the tail). With diagnostics (incl.
    reverse-proxy access logs) printed last, the actual alembic stderr was
    truncated away — exit-36 deploys were undiagnosable (2026-06-03). The fix
    prints the stderr last and caps the reverse-proxy flood.
    """
    script = aws_deploy_i6._build_script(
        env_name="prod",
        aws_region="us-east-1",
        git_ref="origin/master",
        mode="deploy",
    )
    start = script.find("alembic upgrade failed")
    end = script.find("end alembic upgrade stderr")
    fail_block = script[start:end]
    diag_idx = fail_block.find("dump_compose_diagnostics")
    stderr_idx = fail_block.find('cat "$ALEMBIC_STDERR"')
    assert start != -1 and end != -1
    assert diag_idx != -1 and stderr_idx != -1
    assert diag_idx < stderr_idx, (
        "alembic stderr must be printed AFTER dump_compose_diagnostics so it "
        "survives the SSM output tail cap"
    )
    # reverse-proxy access logs capped low so they don't flood the tail window.
    assert "logs --tail=15 reverse-proxy" in script
    # WEB_CID resolution is defensive against a transient multi-id / zombie.
    assert "ps -q web | head -n1" in script
    # #1431: flask db exec must pin FLASK_APP so app→migrations resolution is
    # deterministic (a bare `flask` relies on auto-discovery → "Can't locate
    # revision" exit-36 flakes). All three db commands must set it.
    assert script.count("docker exec -e FLASK_APP=run.py") >= 3


def test_build_script_asserts_alembic_current_equals_heads_after_upgrade() -> None:
    """AC: post-deploy assertion that flask db current == flask db heads."""
    script = aws_deploy_i6._build_script(
        env_name="prod",
        aws_region="us-east-1",
        git_ref="origin/master",
        mode="deploy",
    )
    assert "flask db current" in script
    assert "flask db heads" in script
    # Drift exit code, distinct from upgrade failure (36).
    assert "exit 37" in script


def test_build_script_migration_targets_pinned_web_container() -> None:
    """#1405: migrate/drift must target the pinned $WEB_CID, not `compose exec web`.

    Re-resolving the ``web`` service by name can hit a stale one-off container
    (``auraxis-web-run-*``) with an older migration set, making the upgrade a
    no-op and the drift gate pass against the wrong head — the deploy reports
    success while the live container serves new code against an un-migrated DB.
    """
    script = aws_deploy_i6._build_script(
        env_name="prod",
        aws_region="us-east-1",
        git_ref="origin/master",
        mode="deploy",
    )
    # Upgrade + drift queries must use the captured container id (#1431 pins
    # FLASK_APP for deterministic app→migrations resolution).
    assert 'docker exec -e FLASK_APP=run.py "$WEB_CID" flask db current' in script
    assert 'docker exec -e FLASK_APP=run.py "$WEB_CID" flask db heads' in script
    # upgrade spans two lines; assert the pinned-container prefix and the command.
    assert 'docker exec -e FLASK_APP=run.py "$WEB_CID"' in script
    assert "flask db upgrade" in script
    # And must NOT re-resolve the service by name for these commands.
    assert "exec -T web flask db upgrade" not in script
    assert "exec -T web flask db current" not in script
    assert "exec -T web flask db heads" not in script


def test_build_script_rollback_does_not_run_flask_db_upgrade() -> None:
    """Rollback must NOT run migrations — schema downgrades are out of scope."""
    script = aws_deploy_i6._build_script(
        env_name="prod",
        aws_region="us-east-1",
        git_ref=None,
        mode="rollback",
    )
    # Note: the script template is the same for deploy and rollback; the
    # migration block must be gated by MODE so it only runs on deploy.
    # We assert the gate is present.
    assert 'if [ "$MODE" = "deploy" ]; then' in script or (
        '[ "$MODE" = "deploy" ]' in script
    )


def test_extract_invocation_report_truncates_and_maps_fields() -> None:
    invocation = {
        "Status": "Failed",
        "StatusDetails": "ExecutionTimedOut",
        "ResponseCode": 124,
        "ExecutionStartDateTime": "2026-03-22T10:00:00Z",
        "ExecutionEndDateTime": "2026-03-22T10:05:00Z",
        "StandardOutputUrl": "stdout-url",
        "StandardErrorUrl": "stderr-url",
        "StandardOutputContent": "A" * 15,
        "StandardErrorContent": "B" * 15,
    }

    report = aws_deploy_i6._extract_invocation_report(
        invocation,
        instance_id="i-dev",
        command_id="cmd-123",
    )

    assert report["instance_id"] == "i-dev"
    assert report["command_id"] == "cmd-123"
    assert report["status"] == "Failed"
    assert report["status_details"] == "ExecutionTimedOut"
    assert report["response_code"] == 124
    assert report["stdout_tail"] == "A" * 15
    assert report["stderr_tail"] == "B" * 15


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
            "StandardOutputContent": "deploy stdout",
            "StandardErrorContent": "deploy stderr",
        }

    monkeypatch.setattr(aws_deploy_i6, "_run_aws", fake_run_aws)
    ctx = aws_deploy_i6.AwsCtx(profile="", region="us-east-1")

    with pytest.raises(aws_deploy_i6.SsmCommandFailed) as exc_info:
        aws_deploy_i6._wait(ctx, command_id="cmd-123", instance_id="i-dev")

    report = exc_info.value.report
    assert report["command_id"] == "cmd-123"
    assert report["instance_id"] == "i-dev"
    assert report["status"] == "Failed"
    assert "deploy stderr" in report["stderr_tail"]


def test_write_diagnostics_json_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "report.json"
    payload = {"status": "Success", "command_id": "cmd-123"}

    aws_deploy_i6._write_diagnostics_json(str(target), payload)

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

    monkeypatch.setattr(aws_deploy_i6.subprocess, "run", fake_run)
    ctx = aws_deploy_i6.AwsCtx(profile="", region="us-east-1")

    data = aws_deploy_i6._run_aws(ctx, ["sts", "get-caller-identity"])

    assert data == {"ok": True}
    assert "--profile" not in captured["cmd"]
    assert "--region" in captured["cmd"]
