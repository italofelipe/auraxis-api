def test_healthz_is_public(client) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    # `commit` (SHA do build, "unknown" em dev/local) foi adicionado para
    # detecção de drift de imagem — ver #1533. Não é mais igualdade exata.
    assert "commit" in body
