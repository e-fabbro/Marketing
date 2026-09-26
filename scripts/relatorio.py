#!/usr/bin/env python3
"""Relatório semanal/mensal (ANALISTA) e proposta de tráfego (TRÁFEGO), por delegação, com números só do banco.

  relatorio.py preparar --tipo semanal --semana AAAA-MM-DD     (segunda-feira) → tabelas determinísticas +
                                                                 prompt do ANALISTA em relatorios/prompt_analista_<id>.md
  relatorio.py preparar --tipo mensal  --mes AAAA-MM
  relatorio.py preparar --tipo trafego --dias 7                → prompt do TRÁFEGO em relatorios/prompt_trafego_<data>.md
  relatorio.py entregar --id <id> --arquivo <resposta>          → valida números, grava relatorios/<id>.md

Validação: qualquer número na resposta do modelo que não exista no extrato (ou não seja variação % calculável
a partir dele) reprova a entrega. É a garantia do critério de sucesso 4 ("nenhum número estimado").
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
import especialista  # noqa: E402
import metricas  # noqa: E402
from comum import RAIZ, agora_iso, caminho_db, carregar_config  # noqa: E402

NUM = re.compile(r"(?<![\w/.-])[-+]?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?%?|(?<![\w/.-])[-+]?\d+(?:[.,]\d+)?%?")


def _numeros_texto(texto: str) -> set[str]:
    """Números normalizados (sem separador de milhar, ponto decimal, sem sinal), ignorando datas/ids."""
    limpo = re.sub(r"\d{4}-\d{2}-\d{2}(T[\d:]+Z)?", " ", texto)      # datas e timestamps
    limpo = re.sub(r"\bid\s*\d+|\b\d{6,}\b", " ", limpo)               # ids longos
    saida = set()
    for m in NUM.finditer(limpo):
        s = m.group(0).rstrip("%").lstrip("+-")
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):        # 15.000 (pt-BR) = quinze mil, não 15,0
            s = s.replace(".", "")
        elif s.count(",") == 1 and s.count(".") == 0:
            s = s.replace(",", ".")
        elif s.count(".") > 1 or (s.count(",") >= 1 and s.count(".") == 1):
            s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
        try:
            v = float(s)
        except ValueError:
            continue
        if v.is_integer() and abs(v) < 10:     # "3 linhas", "2 semanas": não são métricas
            continue
        saida.add(f"{v:.2f}")
    return saida


def _numeros_dados(ex: dict, ex_ant: dict | None) -> set[str]:
    base = set()
    def add(v):
        if isinstance(v, (int, float)) and v is not None:
            base.add(f"{float(v):.2f}")
    for t in ex["totais"].values():
        for k, v in t.items():
            add(v)
    for e in ex["entidades"].values():
        for d in e["dias"].values():
            for v in d.values():
                add(v)
    tot = {"custo": 0.0, "cliques": 0, "impressoes": 0, "conversoes": 0.0}
    for t in ex["totais"].values():
        for k in tot:
            tot[k] += t[k]
    for v in tot.values():
        add(round(v, 2))
    if ex_ant:
        for t in ex_ant["totais"].values():
            for v in t.values():
                add(v)
        # variações percentuais calculáveis entre semanas (mesma entidade e totais)
        for ent, t in ex["totais"].items():
            ta = ex_ant["totais"].get(ent)
            if ta:
                for k in ("custo", "cliques", "impressoes", "conversoes", "cpc", "cpa"):
                    if t.get(k) and ta.get(k):
                        add(round((t[k] - ta[k]) / ta[k] * 100, 1)); add(round((t[k] - ta[k]) / ta[k] * 100, 0))
    return base


def validar_numeros(texto: str, ex: dict, ex_ant: dict | None) -> list[str]:
    """Devolve os números do texto que não têm origem nos dados (vazio = ok)."""
    permitidos = _numeros_dados(ex, ex_ant)
    return sorted(n for n in _numeros_texto(texto) if n not in permitidos)


def _semana(seg: str) -> tuple[str, str]:
    d = dt.date.fromisoformat(seg)
    return d.isoformat(), (d + dt.timedelta(days=6)).isoformat()


def preparar(tipo: str, *, raiz: Path, con, config: dict, semana: str | None = None, mes: str | None = None, dias: int = 7) -> dict:
    (raiz / "relatorios").mkdir(exist_ok=True)
    if tipo == "semanal":
        de, ate = _semana(semana)
        de_ant, ate_ant = _semana((dt.date.fromisoformat(semana) - dt.timedelta(days=7)).isoformat())
        rid, nome = f"semanal_{semana}", "analista"
    elif tipo == "mensal":
        ini = dt.date.fromisoformat(mes + "-01")
        fim = (ini.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        de, ate = ini.isoformat(), fim.isoformat()
        ini_ant = (ini - dt.timedelta(days=1)).replace(day=1)
        de_ant, ate_ant = ini_ant.isoformat(), (ini - dt.timedelta(days=1)).isoformat()
        rid, nome = f"mensal_{mes}", "analista"
    else:
        ate = (dt.date.today() - dt.timedelta(days=1)); de = ate - dt.timedelta(days=dias - 1)
        de, ate = de.isoformat(), ate.isoformat()
        de_ant, ate_ant = (dt.date.fromisoformat(de) - dt.timedelta(days=dias)).isoformat(), (dt.date.fromisoformat(de) - dt.timedelta(days=1)).isoformat()
        rid, nome = f"trafego_{ate}", "trafego"
    ex = metricas.extrato(con, de, ate, raiz)
    ex_ant = metricas.extrato(con, de_ant, ate_ant, raiz)
    pecas = [dict(r) for r in con.execute("SELECT id, formato, estado, atualizado_em FROM pecas WHERE estado IN ('PUBLICADO','MEDIDO') AND atualizado_em BETWEEN ? AND ?", (de, ate + "T23:59:59Z"))]
    reprov = []
    for f in (raiz / "dados").glob("ads_reprovados_*.json"):
        reprov += json.loads(f.read_text(encoding="utf-8")).get("dados", [])
    contexto = (f"# Tipo: {tipo} · id {rid}\n\n## Período atual ({de} a {ate})\n{metricas.extrato_md(ex)}\n\n"
                f"## Período anterior ({de_ant} a {ate_ant})\n{metricas.extrato_md(ex_ant)}\n\n"
                f"## Dados brutos por dia (JSON)\n{json.dumps(ex['entidades'], ensure_ascii=False)}\n\n"
                f"## Peças publicadas no período\n{json.dumps(pecas, ensure_ascii=False)}\n\n"
                f"## Anúncios reprovados (última coleta)\n{json.dumps(reprov, ensure_ascii=False)}\n\n"
                f"## Metas/verba (config)\n{json.dumps(config.get('google_ads', {}), ensure_ascii=False)}\n\n"
                "REGRA: use SOMENTE números que apareçam acima (ou variações % calculadas a partir deles). "
                "Qualquer outro número reprova o relatório. Seções sem dado: escreva 'sem dados coletados'.")
    prep = especialista.preparar(nome, raiz=raiz, contexto_extra=contexto, config=config, pasta_prompt=raiz / "relatorios")
    prompt = raiz / "relatorios" / f"prompt_{nome}_{rid}.md"
    prep["prompt"].rename(prompt)
    meta = {"id": rid, "tipo": tipo, "especialista": nome, "de": de, "ate": ate, "de_ant": de_ant, "ate_ant": ate_ant,
            "prompt": str(prompt), "emitido_em": agora_iso(), "modelo": prep["modelo"]}
    (raiz / "relatorios" / f"{rid}.pendente.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"acao": "delegar", "especialista": nome, "modelo": prep["modelo"], "prompt": str(prompt), "id": rid,
            "instrucao": f"delegate_task com o conteúdo do prompt; depois relatorio.py entregar --id {rid} --arquivo <resposta>"}


def entregar(rid: str, texto: str, *, raiz: Path, con, config: dict) -> dict:
    meta_p = raiz / "relatorios" / f"{rid}.pendente.json"
    if not meta_p.exists():
        raise RuntimeError(f"{rid}: nada pendente; rode `preparar` primeiro")
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    ex = metricas.extrato(con, meta["de"], meta["ate"], raiz)
    ex_ant = metricas.extrato(con, meta["de_ant"], meta["ate_ant"], raiz)
    corpo = especialista.extrair_bloco(texto)
    invalidos = validar_numeros(corpo, ex, ex_ant)
    if invalidos:
        raise RuntimeError(f"{rid}: números sem origem nos dados: {', '.join(invalidos)}; o relatório continua pendente")
    destino = raiz / "relatorios" / f"{rid}.md" if meta["tipo"] != "trafego" else raiz / "relatorios" / f"proposta_ads_{meta['ate']}.md"
    especialista.entregar(meta["especialista"], texto, raiz=raiz, con=con, saida=destino, config=config,
                          prompt_chars=len(Path(meta["prompt"]).read_text(encoding="utf-8")), modelo=meta.get("modelo"))
    cab = f"<!-- gerado {agora_iso()} · fontes: {', '.join(ex['fontes']) or 'nenhuma'} · coletas: {', '.join(ex['coletas'][-3:]) or 'nenhuma'} · números validados contra dados/agencia.db -->\n"
    destino.write_text(cab + destino.read_text(encoding="utf-8"), encoding="utf-8")
    meta_p.unlink()
    return {"acao": "fim", "arquivo": str(destino), "periodo": [meta["de"], meta["ate"]]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raiz", default=str(RAIZ))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("preparar"); s.add_argument("--tipo", choices=["semanal", "mensal", "trafego"], required=True)
    s.add_argument("--semana"); s.add_argument("--mes"); s.add_argument("--dias", type=int, default=7)
    s = sub.add_parser("entregar"); s.add_argument("--id", required=True); s.add_argument("--arquivo", required=True)
    a = ap.parse_args(argv)
    raiz = Path(a.raiz)
    config = carregar_config(raiz)
    con = db.inicializar(caminho_db(config, raiz))
    if a.cmd == "preparar":
        if a.tipo == "semanal" and not a.semana:
            ap.error("--semana AAAA-MM-DD (segunda-feira)")
        if a.tipo == "mensal" and not a.mes:
            ap.error("--mes AAAA-MM")
        print(json.dumps(preparar(a.tipo, raiz=raiz, con=con, config=config, semana=a.semana, mes=a.mes, dias=a.dias), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(entregar(a.id, Path(a.arquivo).read_text(encoding="utf-8"), raiz=raiz, con=con, config=config), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
