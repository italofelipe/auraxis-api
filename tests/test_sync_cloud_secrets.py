from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import sync_cloud_secrets


def _completed_process(
    stdout: str, returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["aws"],
        returncode=returncode,
        stdout=stdout,
        stderr="error",
    )


def test_load_ssm_parameters_maps_path_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = """
    {
      "Parameters": [
        {"Name": "/auraxis/prod/SECRET_KEY", "Value": "sk"},
        {"Name": "/auraxis/prod/JWT_SECRET_KEY", "Value": "jwt"}
      ]
    }
    """.strip()

    monkeypatch.setattr(
        sync_cloud_secrets.subprocess,
        "run",
        lambda *args, **kwargs: _completed_process(payload),
    )

    values = sync_cloud_secrets.load_ssm_parameters("/auraxis/prod", "us-east-1")
    assert values["SECRET_KEY"] == "sk"
    assert values["JWT_SECRET_KEY"] == "jwt"


def test_load_secrets_manager_reads_json_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = """
    {"SecretString":"{\\"SECRET_KEY\\":\\"sk\\",\\"DB_HOST\\":\\"db\\"}"}
    """.strip()

    monkeypatch.setattr(
        sync_cloud_secrets.subprocess,
        "run",
        lambda *args, **kwargs: _completed_process(payload),
    )

    values = sync_cloud_secrets.load_secrets_manager("auraxis/prod/app", "us-east-1")
    assert values["SECRET_KEY"] == "sk"
    assert values["DB_HOST"] == "db"


def test_write_env_file_escapes_unsafe_values(tmp_path: Path) -> None:
    output = tmp_path / ".env.runtime"
    sync_cloud_secrets.write_env_file(
        output,
        {
            "SECRET_KEY": "abc 123",
            "DB_HOST": "db",
        },
    )

    content = output.read_text(encoding="utf-8")
    assert "DB_HOST=db" in content
    assert "SECRET_KEY='abc 123'" in content


def test_validate_required_keys_raises_when_missing() -> None:
    with pytest.raises(
        sync_cloud_secrets.SecretSyncError, match="Missing required keys"
    ):
        sync_cloud_secrets._validate_required_keys(
            {"SECRET_KEY": "sk"},
            {"SECRET_KEY", "JWT_SECRET_KEY"},
        )


def test_parse_env_file_ignores_comments_and_quotes(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.base"
    env_file.write_text(
        "# comment\nDOMAIN=dev.api.auraxis.com.br\nCERTBOT_EMAIL=''\n",
        encoding="utf-8",
    )

    values = sync_cloud_secrets.parse_env_file(env_file)

    assert values["DOMAIN"] == "dev.api.auraxis.com.br"
    assert values["CERTBOT_EMAIL"] == ""


def test_merge_env_values_applies_cloud_then_explicit_overrides() -> None:
    merged = sync_cloud_secrets.merge_env_values(
        base_values={"DOMAIN": "api.auraxis.com.br", "AURAXIS_ENV": "prod"},
        cloud_values={"SECRET_KEY": "sk", "DOMAIN": "from-cloud"},
        override_values={"DOMAIN": "dev.api.auraxis.com.br"},
    )

    assert merged["SECRET_KEY"] == "sk"
    assert merged["AURAXIS_ENV"] == "prod"
    assert merged["DOMAIN"] == "dev.api.auraxis.com.br"
