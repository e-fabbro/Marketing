#!/usr/bin/env python3
"""Encadeamento ESTRATEGISTA → REDATOR → DESIGNER (arte.yaml + render) → COMPLIANCE, com estado via transicao.py.

  pauta  --semana 2026-09-28 [--criar]      gera conteudo/pauta_<semana>.yaml e, com --criar, as peças em PAUTA
  peca   --peca <id> [--sem-llm-compliance] leva a peça de PAUTA até AGUARDANDO_HUMANO, REPROVADO/ESCALAR
                                            ou de volta a RASCUNHO (máx. voltas), sempre pelo gate

O DUDS chama este script; ele não fala com humanos. Erros sobem como exceção (código 1).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compliance  # noqa: E402
import db  # noqa: E402
import especialista  # noqa: E402
import render_arte  # noqa: E402
import render_cliente  # noqa: E402
import transicao  # noqa: E402
from comum import RAIZ, caminho_db, carregar_config, logger  # noqa: E402


def gerar_pauta(semana: str, *, raiz: Path, con, cliente, config: dict, criar: bool, autor: str = "estrategista") -> Path:
    anteriores = sorted((raiz / "conteudo").glob("pauta_*.yaml"))[-4:]
    ctx = [f"Semana alvo (segunda-feira): {semana}"]
    for p in anteriores:
        ctx.append(f"## Pauta anterior {p.name}\n{p.read_text(encoding='utf-8')}")
    saida = raiz / "conteudo" / f"pauta_{semana}.yaml"
    especialista.executar("estrategista", raiz=raiz, con=con, cliente=cliente, contexto_extra="\n".join(ctx), saida=saida, config=config)
    pauta = yaml.safe_load(saida.read_text(encoding="utf-8"))
    if criar:
        for p in pauta["pecas"]:
            transicao.criar_peca(con, raiz, id=p["id"], canal=p["canal"], formato=p["formato"], pilar=str(p["pilar"]),
                                 objetivo=p["objetivo"], cta=p["cta"], autor=autor, motivo=f"pauta {semana}",
                                 extras={k: v for k, v in p.items() if k not in ("id", "canal", "formato", "pilar", "objetivo", "cta")})
    return saida


def processar_peca(peca_id: str, *, raiz: Path, con, cliente, config: dict, cliente_compliance="mesmo") -> str:
    """Retorna o estado final. cliente_compliance: 'mesmo' usa `cliente`; None = só regras."""
    log = logger("pipeline", raiz)
    cli_comp = cliente if cliente_compliance == "mesmo" else cliente_compliance
    estado = con.execute("SELECT estado FROM pecas WHERE id=?", (peca_id,)).fetchone()
    if not estado:
        raise transicao.TransicaoInvalida(f"peça {peca_id} não existe")
    estado = estado[0]
    formato = con.execute("SELECT formato FROM pecas WHERE id=?", (peca_id,)).fetchone()[0]
    if estado not in ("PAUTA", "RASCUNHO", "AJUSTAR", "REPROVADO"):
        raise transicao.TransicaoInvalida(f"{peca_id} está em {estado}; o pipeline só retoma de PAUTA/RASCUNHO/AJUSTAR/REPROVADO")
    if estado in ("PAUTA", "AJUSTAR", "REPROVADO"):
        estado = transicao.mover(con, raiz, peca_id, "RASCUNHO", "duds", "pipeline: início da rodada", config)["estado"]

    while True:
        contexto = ""
        pasta = raiz / "conteudo" / peca_id
        if (pasta / "compliance.json").exists():
            contexto += "Parecer de compliance anterior (corrija tudo que falhou):\n" + (pasta / "compliance.json").read_text(encoding="utf-8")
        if (pasta / "ajuste.md").exists():
            contexto += "\nPedido de ajuste do humano:\n" + (pasta / "ajuste.md").read_text(encoding="utf-8")
        especialista.executar("redator", raiz=raiz, con=con, cliente=cliente, peca_id=peca_id, contexto_extra=contexto, config=config)
        # DESIGNER: arte.yaml (LLM) → validação → PNGs (render no host ou local). Arte inválida volta ao
        # designer uma vez com o erro; se persistir, a exceção sobe (nunca segue sem arte).
        pasta.joinpath("copy.md")  # (já existe)
        erro_arte = ""
        for tentativa in (1, 2):
            especialista.executar("designer", raiz=raiz, con=con, cliente=cliente, peca_id=peca_id,
                                  contexto_extra=(f"Templates disponíveis: {', '.join(render_arte.FORMATOS_POR_TEMPLATE)}. "
                                                  f"Formato da peça: {formato}." + (f"\nERRO na tentativa anterior: {erro_arte}. Corrija." if erro_arte else "")),
                                  config=config)
            try:
                pngs = render_cliente.renderizar_peca(peca_id, raiz)
                break
            except render_arte.ArteInvalida as exc:
                erro_arte = str(exc)
                log.warning("%s arte inválida (tentativa %d): %s", peca_id, tentativa, exc)
        else:
            raise render_arte.ArteInvalida(f"{peca_id}: arte.yaml inválido após 2 tentativas: {erro_arte}")
        transicao.mover(con, raiz, peca_id, "ARTE", "designer", f"arte renderizada: {', '.join(pngs)}", config)
        transicao.mover(con, raiz, peca_id, "COMPLIANCE", "duds", "gate obrigatório", config)
        parecer = compliance.avaliar_peca(peca_id, raiz=raiz, con=con, cliente=cli_comp, config=config)
        resultado = parecer["resultado"]
        peca = transicao.mover(con, raiz, peca_id, resultado, "compliance", parecer.get("motivo_escalar") or "; ".join(parecer["trechos_problematicos"]) or "ok", config)
        log.info("%s compliance=%s voltas=%s", peca_id, resultado, peca["voltas_compliance"])
        if resultado == "APROVADO_COMPLIANCE":
            return transicao.mover(con, raiz, peca_id, "AGUARDANDO_HUMANO", "duds", "pronto para aprovação humana", config)["estado"]
        if resultado == "ESCALAR":
            return "ESCALAR"
        # REPROVADO: volta ao rascunho até o limite; acima dele, escala
        max_voltas = int(config["compliance"]["max_voltas"])
        if peca["voltas_compliance"] > max_voltas:
            return transicao.mover(con, raiz, peca_id, "ESCALAR", "duds", f"{peca['voltas_compliance']}ª reprovação; decisão humana", config)["estado"]
        transicao.mover(con, raiz, peca_id, "RASCUNHO", "duds", "nova rodada após reprovação", config)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raiz", default=str(RAIZ))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s1 = sub.add_parser("pauta"); s1.add_argument("--semana", required=True); s1.add_argument("--criar", action="store_true")
    s2 = sub.add_parser("peca"); s2.add_argument("--peca", required=True); s2.add_argument("--sem-llm-compliance", action="store_true")
    a = ap.parse_args(argv)
    raiz = Path(a.raiz)
    config = carregar_config(raiz)
    con = db.inicializar(caminho_db(config, raiz))
    cliente = especialista.cliente_padrao(raiz)
    if a.cmd == "pauta":
        print(f"ok: {gerar_pauta(a.semana, raiz=raiz, con=con, cliente=cliente, config=config, criar=a.criar)}")
    else:
        print(f"{a.peca}: {processar_peca(a.peca, raiz=raiz, con=con, cliente=cliente, config=config, cliente_compliance=None if a.sem_llm_compliance else 'mesmo')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
