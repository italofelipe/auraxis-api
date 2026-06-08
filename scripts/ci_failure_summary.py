#!/usr/bin/env python3
"""Classify CI suite failures and publish actionable diagnostics summaries."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as ET


@dataclass(frozen=True)
class FailureCategory:
    code: str
    summary: str
    probable_cause: str


@dataclass(frozen=True)
class NewmanFailure:
    suites: int
    tests: int
    failures: int
    first_failure_name: str | None
    first_failure_message: str | None


@dataclass(frozen=True)
class BootstrapAttempt:
    phase: str
    attempt: int
    success: bool
    detail: str
    duration_ms: int | None


@dataclass(frozen=True)
class BootstrapDetails:
    status: str
    failed_phase: str | None
    total_duration_ms: int | None
    attempts: list[BootstrapAttempt] = field(default_factory=list)
    diagnostics: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class LatencyDetails:
    all_within_budget: bool
    offenders: list[str]


@dataclass(frozen=True)
class SummaryReport:
    job_name: str
    profile: str
    job_status: str
    category: FailureCategory
    step_outcomes: dict[str, str]
    bootstrap: BootstrapDetails | None
    newman: NewmanFailure | None
    latency: LatencyDetails | None
    artifacts: list[str]


SUCCESS_CATEGORY = FailureCategory(
    code="success",
    summary="Job concluído sem falhas classificáveis.",
    probable_cause="Nenhuma ação corretiva necessária.",
)
RUNTIME_IMAGE_CATEGORY = FailureCategory(
    code="infra.runtime_image_supply_chain",
    summary="Falha ao carregar ou disponibilizar a imagem canônica da suíte.",
    probable_cause=(
        "Artifact ausente/corrompido ou problema no supply chain de imagens."
    ),
)
BOOT_CATEGORY = FailureCategory(
    code="infra.stack_boot",
    summary="A stack local da suíte não subiu corretamente.",
    probable_cause="Falha de compose/containers durante o bootstrap.",
)
MIGRATION_CATEGORY = FailureCategory(
    code="infra.stack_migration",
    summary="A stack subiu, mas a migração não convergiu.",
    probable_cause="Banco não pronto, migration quebrada ou drift estrutural.",
)
HEALTH_CATEGORY = FailureCategory(
    code="infra.stack_readiness",
    summary="A aplicação não ficou saudável após bootstrap/migração.",
    probable_cause="Readiness incompleta, boot lento ou falha de runtime.",
)
POSTMAN_CATEGORY = FailureCategory(
    code="contract.postman_assertion",
    summary="O gate funcional falhou em asserções do Newman/Postman.",
    probable_cause="Regressão funcional ou contrato divergente no runtime.",
)
LATENCY_CATEGORY = FailureCategory(
    code="performance.latency_budget",
    summary="A suite passou funcionalmente, mas estourou o budget de latência.",
    probable_cause="Regressão de performance acima do limite configurado.",
)
UNKNOWN_CATEGORY = FailureCategory(
    code="unknown.unclassified",
    summary="O job falhou sem classificação canônica suficiente.",
    probable_cause=(
        "A trilha não produziu evidência bastante para diagnóstico automático."
    ),
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object JSON in {path}")
    return payload


def _load_bootstrap(path: Path | None) -> BootstrapDetails | None:
    if path is None or not path.exists():
        return None
    payload = _load_json(path)
    attempts: list[BootstrapAttempt] = []
    for raw_attempt in payload.get("attempts", []):
        if not isinstance(raw_attempt, dict):
            continue
        attempts.append(
            BootstrapAttempt(
                phase=str(raw_attempt.get("phase", "unknown")),
                attempt=int(raw_attempt.get("attempt", 0)),
                success=bool(raw_attempt.get("success", False)),
                detail=str(raw_attempt.get("detail", "")),
                duration_ms=(
                    int(raw_attempt["duration_ms"])
                    if isinstance(raw_attempt.get("duration_ms"), int)
                    else None
                ),
            )
        )
    diagnostics = [
        artifact
        for artifact in payload.get("diagnostics", [])
        if isinstance(artifact, dict)
    ]
    return BootstrapDetails(
        status=str(payload.get("status", "unknown")),
        failed_phase=(
            str(payload["failed_phase"])
            if payload.get("failed_phase") is not None
            else None
        ),
        total_duration_ms=(
            int(payload["total_duration_ms"])
            if isinstance(payload.get("total_duration_ms"), int)
            else None
        ),
        attempts=attempts,
        diagnostics=[{str(k): str(v) for k, v in item.items()} for item in diagnostics],
    )


def _load_newman(path: Path | None) -> NewmanFailure | None:
    if path is None or not path.exists():
        return None
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    suites = 0
    tests = 0
    failures = 0
    first_failure_name: str | None = None
    first_failure_message: str | None = None
    for testsuite in root.iter("testsuite"):
        suites += 1
        tests += int(testsuite.attrib.get("tests", "0"))
        failures += int(testsuite.attrib.get("failures", "0"))
    for testcase in root.iter("testcase"):
        failure = testcase.find("failure")
        if failure is not None:
            first_failure_name = testcase.attrib.get("name")
            first_failure_message = failure.attrib.get("message") or (
                failure.text.strip() if failure.text else None
            )
            break
    return NewmanFailure(
        suites=suites,
        tests=tests,
        failures=failures,
        first_failure_name=first_failure_name,
        first_failure_message=first_failure_message,
    )


def _load_latency(path: Path | None) -> LatencyDetails | None:
    if path is None or not path.exists():
        return None
    payload = _load_json(path)
    routes = payload.get("routes", {})
    offenders: list[str] = []
    if isinstance(routes, dict):
        for route_name, route_payload in routes.items():
            if isinstance(route_payload, dict) and (
                route_payload.get("within_budget") is False
            ):
                offenders.append(str(route_name))
    return LatencyDetails(
        all_within_budget=bool(payload.get("all_within_budget", False)),
        offenders=offenders,
    )


def _bootstrap_category(phase: str | None) -> FailureCategory:
    if phase == "migration":
        return MIGRATION_CATEGORY
    if phase == "health":
        return HEALTH_CATEGORY
    return BOOT_CATEGORY


def _classify_from_steps(
    *,
    job_status: str,
    step_outcomes: dict[str, str],
    bootstrap: BootstrapDetails | None,
) -> FailureCategory | None:
    if job_status == "success":
        return SUCCESS_CATEGORY
    if step_outcomes.get("load_image") == "failure":
        return RUNTIME_IMAGE_CATEGORY
    if step_outcomes.get("bootstrap") == "failure":
        return _bootstrap_category(bootstrap.failed_phase if bootstrap else None)
    if step_outcomes.get("newman") == "failure":
        return POSTMAN_CATEGORY
    if step_outcomes.get("latency") == "failure":
        return LATENCY_CATEGORY
    return None


def _classify_from_reports(
    *,
    bootstrap: BootstrapDetails | None,
    newman: NewmanFailure | None,
    latency: LatencyDetails | None,
) -> FailureCategory | None:
    if bootstrap is not None and bootstrap.status == "failed":
        return _bootstrap_category(bootstrap.failed_phase)
    if newman is not None and newman.failures > 0:
        return POSTMAN_CATEGORY
    if latency is not None and not latency.all_within_budget:
        return LATENCY_CATEGORY
    return None


def _classify_failure(
    *,
    job_status: str,
    step_outcomes: dict[str, str],
    bootstrap: BootstrapDetails | None,
    newman: NewmanFailure | None,
    latency: LatencyDetails | None,
) -> FailureCategory:
    from_steps = _classify_from_steps(
        job_status=job_status,
        step_outcomes=step_outcomes,
        bootstrap=bootstrap,
    )
    if from_steps is not None:
        return from_steps
    from_reports = _classify_from_reports(
        bootstrap=bootstrap,
        newman=newman,
        latency=latency,
    )
    if from_reports is not None:
        return from_reports
    return UNKNOWN_CATEGORY


def _collect_artifacts(
    reports_dir: Path,
    bootstrap_path: Path | None,
    newman_path: Path | None,
    latency_path: Path | None,
) -> list[str]:
    artifacts: list[str] = []
    seen: set[str] = set()

    def append(path: Path) -> None:
        normalized = str(path)
        if normalized not in seen:
            artifacts.append(normalized)
            seen.add(normalized)

    for path in (bootstrap_path, newman_path, latency_path):
        if path is not None and path.exists():
            append(path)
    if reports_dir.exists():
        for candidate in sorted(reports_dir.glob("*")):
            if candidate.is_file():
                append(candidate)
    return artifacts


def _render_summary(report: SummaryReport) -> str:
    lines = [
        f"## {report.job_name} diagnostics",
        "",
        f"- Profile: `{report.profile}`",
        f"- Job status: `{report.job_status}`",
        f"- Failure category: `{report.category.code}`",
        f"- Summary: {report.category.summary}",
        f"- Probable cause: {report.category.probable_cause}",
    ]
    if report.bootstrap is not None:
        lines.append(
            "- Bootstrap: "
            f"status=`{report.bootstrap.status}` "
            f"phase=`{report.bootstrap.failed_phase or 'ok'}` "
            f"total_duration_ms=`{report.bootstrap.total_duration_ms or 0}`"
        )
    if report.newman is not None:
        lines.append(
            "- Newman: "
            f"suites=`{report.newman.suites}` "
            f"tests=`{report.newman.tests}` "
            f"failures=`{report.newman.failures}`"
        )
        if report.newman.first_failure_name:
            lines.append(
                f"- Newman first failure: `{report.newman.first_failure_name}`"
            )
    if report.latency is not None:
        offenders = ", ".join(report.latency.offenders) or "none"
        lines.append(
            "- Latency budget: "
            f"all_within_budget=`{str(report.latency.all_within_budget).lower()}` "
            f"offenders=`{offenders}`"
        )
    if report.step_outcomes:
        step_summary = ", ".join(
            f"{name}={outcome}"
            for name, outcome in sorted(report.step_outcomes.items())
        )
        lines.append(f"- Step outcomes: {step_summary}")
    if report.artifacts:
        lines.append("- Artifacts:")
        lines.extend(f"  - `{artifact}`" for artifact in report.artifacts)
    return "\n".join(lines) + "\n"


def _write_step_summary(content: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write(content)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CI failure taxonomy summary")
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--job-status", required=True)
    parser.add_argument("--reports-dir", required=True)
    parser.add_argument("--bootstrap-report")
    parser.add_argument("--newman-report")
    parser.add_argument("--latency-report")
    parser.add_argument(
        "--step-outcome",
        action="append",
        default=[],
        help="Step outcome in the form name=status",
    )
    parser.add_argument(
        "--write-summary",
        action="store_true",
        help="Append the rendered summary to GITHUB_STEP_SUMMARY when available.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    reports_dir = Path(args.reports_dir)
    bootstrap_path = Path(args.bootstrap_report) if args.bootstrap_report else None
    newman_path = Path(args.newman_report) if args.newman_report else None
    latency_path = Path(args.latency_report) if args.latency_report else None

    step_outcomes: dict[str, str] = {}
    for item in args.step_outcome:
        name, separator, outcome = str(item).partition("=")
        if separator and name and outcome:
            step_outcomes[name] = outcome

    bootstrap = _load_bootstrap(bootstrap_path)
    newman = _load_newman(newman_path)
    latency = _load_latency(latency_path)
    category = _classify_failure(
        job_status=str(args.job_status),
        step_outcomes=step_outcomes,
        bootstrap=bootstrap,
        newman=newman,
        latency=latency,
    )
    report = SummaryReport(
        job_name=str(args.job_name),
        profile=str(args.profile),
        job_status=str(args.job_status),
        category=category,
        step_outcomes=step_outcomes,
        bootstrap=bootstrap,
        newman=newman,
        latency=latency,
        artifacts=_collect_artifacts(
            reports_dir,
            bootstrap_path=bootstrap_path,
            newman_path=newman_path,
            latency_path=latency_path,
        ),
    )
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary_path = reports_dir / "diagnostic-summary.md"
    json_path = reports_dir / "diagnostic-summary.json"
    summary_content = _render_summary(report)
    summary_path.write_text(summary_content, encoding="utf-8")
    json_path.write_text(
        json.dumps(asdict(report), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    if args.write_summary:
        _write_step_summary(summary_content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
