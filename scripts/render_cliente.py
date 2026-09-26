"""Escolhe como renderizar: serviço HTTP no host (AGENCIA_RENDER_URL no .env) ou local (Chromium acessível)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_arte  # noqa: E402
from comum import carregar_env  # noqa: E402


def renderizar_peca(peca_id: str, raiz: Path) -> list[str]:
    env = carregar_env(raiz)
    url = env.get("AGENCIA_RENDER_URL", "").rstrip("/")
    if url:
        import requests
        r = requests.post(f"{url}/render", json={"peca": peca_id},
                          headers={"X-Agencia-Token": env.get("AGENCIA_RENDER_TOKEN", "")}, timeout=300)
        dados = r.json()
        if r.status_code == 422:
            raise render_arte.ArteInvalida(dados.get("erro", "arte.yaml inválido"))
        if r.status_code != 200 or not dados.get("ok"):
            raise RuntimeError(f"render_servico {r.status_code}: {dados.get('erro')}")
        return dados["pngs"]
    return [p.name for p in render_arte.renderizar(raiz / "conteudo" / peca_id, raiz)]
