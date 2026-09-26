#!/usr/bin/env python3
"""Executor determinístico de especialistas (D1): monta prompt = SKILL.md + marca + peça, chama o
endpoint OpenAI-compatível configurado (.env AGENCIA_LLM_BASE_URL/AGENCIA_LLM_API_KEY), grava a saída
no arquivo do especialista e registra tokens em `custos`.

Uso direto (raro; o normal é via pipeline.py):
  PYTHONPATH=vendor python3 scripts/especialista.py redator --peca 2026-09-29_slug
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
from comum import RAIZ, caminho_db, carregar_config, carregar_env, logger  # noqa: E402

# arquivos de marca que cada especialista recebe (seção "Entradas" de cada SKILL.md)
MARCA_POR_ESPECIALISTA = {
    "estrategista": ["marca.md", "personas.md", "pilares.md", "proibidos.md"],
    "redator": ["marca.md", "tom-de-voz.md", "proibidos.md"],
    "designer": ["marca.md"],
    "compliance": ["marca.md", "tom-de-voz.md", "proibidos.md"],
    "trafego": ["marca.md", "proibidos.md"],
    "analista": [],
}
SAIDA = {"estrategista": "pauta.yaml", "redator": "copy.md", "designer": "arte.yaml",
         "compliance": "compliance.json", "trafego": "proposta_ads.md", "analista": "relatorio.md"}


class ClienteLLM:
    """Cliente mínimo para /chat/completions (OpenAI-compatível). Sem SDK para caber em vendor/."""

    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def completar(self, modelo: str, system: str, user: str, temperatura: float, max_tokens: int):
        import requests  # importado aqui para os testes não exigirem rede/pacote
        cab = {"Content-Type": "application/json"}
        if self.api_key:
            cab["Authorization"] = f"Bearer {self.api_key}"
        corpo = {"model": modelo, "temperature": temperatura, "max_tokens": max_tokens,
                 "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        r = requests.post(f"{self.base_url}/chat/completions", json=corpo, headers=cab, timeout=180)
        r.raise_for_status()
        d = r.json()
        uso = d.get("usage", {}) or {}
        return (d["choices"][0]["message"]["content"],
                int(uso.get("prompt_tokens", 0)), int(uso.get("completion_tokens", 0)))


def cliente_padrao(raiz: Path = RAIZ) -> ClienteLLM:
    env = carregar_env(raiz)
    base = env.get("AGENCIA_LLM_BASE_URL")
    if not base:
        raise RuntimeError("AGENCIA_LLM_BASE_URL ausente no .env (proxy do DUDS; ver docs/decisoes.md D1)")
    return ClienteLLM(base, env.get("AGENCIA_LLM_API_KEY", ""))


def _ler(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def montar_system(nome: str, raiz: Path) -> str:
    skill = _ler(raiz / "especialistas" / nome / "SKILL.md")
    partes = [skill, "\n\n# Arquivos da marca (fonte de verdade; campos TODO = não usar)\n"]
    for arq in MARCA_POR_ESPECIALISTA[nome]:
        partes.append(f"\n## brand/{arq}\n{_ler(raiz / 'brand' / arq)}")
    partes.append("\n\nResponda APENAS com o conteúdo do arquivo de saída definido na skill, dentro de um único "
                  "bloco ```; nenhum texto antes ou depois.")
    return "".join(partes)


def montar_user(nome: str, raiz: Path, peca_id: str | None, contexto_extra: str) -> str:
    partes = []
    if peca_id:
        pasta = raiz / "conteudo" / peca_id
        for arq in ("peca.yaml", "copy.md", "arte.yaml", "compliance.json", "ajuste.md"):
            txt = _ler(pasta / arq)
            if txt and not (nome == "compliance" and arq == "compliance.json"):
                partes.append(f"## {arq}\n{txt}\n")
    if contexto_extra:
        partes.append(f"## Contexto adicional\n{contexto_extra}\n")
    return "\n".join(partes) or "Sem contexto adicional."


def extrair_bloco(texto: str) -> str:
    m = re.search(r"```[a-zA-Z]*\n(.*?)```", texto, re.S)
    return (m.group(1) if m else texto).strip() + "\n"


def verificar_teto(con, nome: str, config: dict) -> None:
    custo = config.get("custo", {})
    teto_e = int(custo.get("teto_tokens_mes_por_especialista", 0) or 0)
    teto_t = int(custo.get("teto_tokens_mes_total", 0) or 0)
    if not teto_e and not teto_t:
        return
    mes = "strftime('%Y-%m', timestamp) = strftime('%Y-%m', 'now')"
    if teto_e:
        u = con.execute(f"SELECT COALESCE(SUM(tokens_entrada+tokens_saida),0) FROM custos WHERE especialista=? AND {mes}", (nome,)).fetchone()[0]
        if u >= teto_e:
            raise RuntimeError(f"teto mensal de tokens do {nome} atingido ({u} >= {teto_e}); pare e avise o Fabbro")
    if teto_t:
        u = con.execute(f"SELECT COALESCE(SUM(tokens_entrada+tokens_saida),0) FROM custos WHERE {mes}").fetchone()[0]
        if u >= teto_t:
            raise RuntimeError(f"teto mensal total de tokens atingido ({u} >= {teto_t}); pare e avise o Fabbro")


def executar(nome: str, *, raiz: Path, con, cliente, peca_id: str | None = None,
             contexto_extra: str = "", saida: Path | None = None, config: dict | None = None) -> Path:
    config = config or carregar_config(raiz)
    if nome not in SAIDA:
        raise ValueError(f"especialista desconhecido: {nome}")
    verificar_teto(con, nome, config)
    cfg = config["especialistas"][nome]
    system = montar_system(nome, raiz)
    user = montar_user(nome, raiz, peca_id, contexto_extra)
    texto, t_in, t_out = cliente.completar(cfg["modelo"], system, user, float(cfg["temperatura"]), int(cfg["max_tokens"]))
    conteudo = extrair_bloco(texto)
    if SAIDA[nome].endswith(".json"):
        json.loads(conteudo)               # inválido = exceção, nunca silêncio
    elif SAIDA[nome].endswith(".yaml"):
        yaml.safe_load(conteudo)
    destino = saida or (raiz / "conteudo" / peca_id / SAIDA[nome] if peca_id else raiz / "conteudo" / SAIDA[nome])
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(conteudo, encoding="utf-8")
    con.execute("INSERT INTO custos (especialista, modelo, tokens_entrada, tokens_saida, peca_id) VALUES (?,?,?,?,?)",
                (nome, cfg["modelo"], t_in, t_out, peca_id))
    con.commit()
    logger("especialista", raiz).info("%s peca=%s modelo=%s tokens=%d/%d -> %s", nome, peca_id, cfg["modelo"], t_in, t_out, destino)
    return destino


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("nome", choices=list(SAIDA))
    ap.add_argument("--peca")
    ap.add_argument("--contexto", default="")
    ap.add_argument("--raiz", default=str(RAIZ))
    a = ap.parse_args(argv)
    raiz = Path(a.raiz)
    config = carregar_config(raiz)
    con = db.inicializar(caminho_db(config, raiz))
    p = executar(a.nome, raiz=raiz, con=con, cliente=cliente_padrao(raiz), peca_id=a.peca, contexto_extra=a.contexto, config=config)
    print(f"ok: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
