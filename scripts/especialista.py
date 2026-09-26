#!/usr/bin/env python3
"""Executor de especialistas (D1): monta o prompt = SKILL.md + marca + peça, obtém a resposta do modelo e
valida/grava a saída, registrando tokens em `custos`.

Dois modos, mesma preparação e mesma entrega:
- delegação (padrão, D1c): `preparar()` escreve conteudo/<peça>/prompt_<nome>.md; o DUDS passa esse texto
  ao `delegate_task` e devolve a resposta em `entregar()`. Tokens estimados (chars/4, coluna estimado=1).
- direto (se AGENCIA_LLM_BASE_URL existir no .env): `executar()` chama um endpoint OpenAI-compatível.

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
        import requests
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


def cliente_padrao(raiz: Path = RAIZ):
    """ClienteLLM se houver endpoint direto no .env; None = modo delegação."""
    env = carregar_env(raiz)
    base = env.get("AGENCIA_LLM_BASE_URL")
    return ClienteLLM(base, env.get("AGENCIA_LLM_API_KEY", "")) if base else None


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


def preparar(nome: str, *, raiz: Path, peca_id: str | None = None, contexto_extra: str = "",
             config: dict | None = None, pasta_prompt: Path | None = None) -> dict:
    """Monta o prompt e grava prompt_<nome>.md (delegação). Devolve system/user/parâmetros/caminho."""
    config = config or carregar_config(raiz)
    if nome not in SAIDA:
        raise ValueError(f"especialista desconhecido: {nome}")
    cfg = config["especialistas"][nome]
    system, user = montar_system(nome, raiz), montar_user(nome, raiz, peca_id, contexto_extra)
    pasta = pasta_prompt or (raiz / "conteudo" / peca_id if peca_id else raiz / "conteudo")
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / f"prompt_{nome}.md"
    arquivo.write_text(
        f"# Tarefa para o subagente: especialista {nome.upper()} da Agência REVERA\n"
        f"Modelo sugerido: {cfg['modelo']} · temperatura {cfg['temperatura']} · saída: {SAIDA[nome]}\n"
        f"Você NÃO fala com humanos; devolva só o bloco pedido.\n\n---\n\n{system}\n\n---\n\n# Entrada\n\n{user}\n",
        encoding="utf-8")
    return {"system": system, "user": user, "modelo": cfg["modelo"], "temperatura": float(cfg["temperatura"]),
            "max_tokens": int(cfg["max_tokens"]), "prompt": arquivo, "saida": SAIDA[nome]}


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


def entregar(nome: str, texto: str, *, raiz: Path, con, peca_id: str | None = None, saida: Path | None = None,
             config: dict | None = None, tokens: tuple[int, int] | None = None, prompt_chars: int = 0,
             modelo: str | None = None) -> Path:
    """Valida a resposta do modelo, grava o arquivo de saída e registra custos. Inválido = exceção."""
    config = config or carregar_config(raiz)
    cfg = config["especialistas"][nome]
    conteudo = extrair_bloco(texto)
    if SAIDA[nome].endswith(".json"):
        json.loads(conteudo)
    elif SAIDA[nome].endswith(".yaml"):
        yaml.safe_load(conteudo)
    destino = saida or (raiz / "conteudo" / peca_id / SAIDA[nome] if peca_id else raiz / "conteudo" / SAIDA[nome])
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(conteudo, encoding="utf-8")
    if tokens is None:
        t_in, t_out, est = max(1, prompt_chars // 4), max(1, len(texto) // 4), 1
    else:
        (t_in, t_out), est = tokens, 0
    con.execute("INSERT INTO custos (especialista, modelo, tokens_entrada, tokens_saida, estimado, peca_id) VALUES (?,?,?,?,?,?)",
                (nome, modelo or cfg["modelo"], t_in, t_out, est, peca_id))
    con.commit()
    logger("especialista", raiz).info("%s peca=%s modelo=%s tokens=%d/%d%s -> %s", nome, peca_id, modelo or cfg["modelo"], t_in, t_out, " (est)" if est else "", destino)
    return destino


def executar(nome: str, *, raiz: Path, con, cliente, peca_id: str | None = None,
             contexto_extra: str = "", saida: Path | None = None, config: dict | None = None) -> Path:
    """Modo direto: preparar → chamar o endpoint → entregar."""
    config = config or carregar_config(raiz)
    verificar_teto(con, nome, config)
    p = preparar(nome, raiz=raiz, peca_id=peca_id, contexto_extra=contexto_extra, config=config,
                 pasta_prompt=saida.parent if saida else None)
    texto, t_in, t_out = cliente.completar(p["modelo"], p["system"], p["user"], p["temperatura"], p["max_tokens"])
    return entregar(nome, texto, raiz=raiz, con=con, peca_id=peca_id, saida=saida, config=config, tokens=(t_in, t_out))


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
    cli = cliente_padrao(raiz)
    if cli is None:
        p = preparar(a.nome, raiz=raiz, peca_id=a.peca, contexto_extra=a.contexto, config=config)
        print(f"modo delegação: prompt em {p['prompt']}; devolva a resposta com pipeline.py entregar")
        return 0
    print(f"ok: {executar(a.nome, raiz=raiz, con=con, cliente=cli, peca_id=a.peca, contexto_extra=a.contexto, config=config)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
