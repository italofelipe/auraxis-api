"""Smoke test for the health endpoint — DoD compliance for issue #617."""


def test_health_endpoint_returns_ok(client) -> None:
    """GET /healthz must return HTTP 200 with status=ok (public, no auth required)."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json["status"] == "ok"


def test_health_endpoint_not_5xx(client) -> None:
    """GET /healthz must never return a 5xx response."""
    response = client.get("/healthz")
    assert response.status_code < 500


def test_health_endpoint_exposes_commit_sha(client, monkeypatch) -> None:
    """GET /healthz expõe o commit SHA gravado no build (drift detection).

    Sem AURAXIS_COMMIT_SHA no ambiente → 'unknown' (não quebra dev/local).
    """
    monkeypatch.delenv("AURAXIS_COMMIT_SHA", raising=False)
    assert client.get("/healthz").json["commit"] == "unknown"

    monkeypatch.setenv("AURAXIS_COMMIT_SHA", "abc1234")
    assert client.get("/healthz").json["commit"] == "abc1234"
