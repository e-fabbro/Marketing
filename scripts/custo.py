#!/usr/bin/env python3
"""Custo de API por especialista (tokens; estimados quando a delegação não devolve usage) e teto mensal.
  custo.py [--mes AAAA-MM] [--json]
Sai com código 3 se algum teto de config/agencia.yaml estiver estourado.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
from comum import RAIZ, caminho_db, carregar_config  # noqa: E402


def resumo(con, config: dict, mes: str) -> dict:
    rows = con.execute("""SELECT especialista, modelo, SUM(tokens_entrada) e, SUM(tokens_saida) s, SUM(estimado) est, COUNT(*) n
                          FROM custos WHERE strftime('%Y-%m', timestamp)=? GROUP BY especialista, modelo ORDER BY especialista""", (mes,)).fetchall()
    por_esp: dict[str, dict] = {}
    for r in rows:
        d = por_esp.setdefault(r["especialista"], {"tokens": 0, "chamadas": 0, "estimadas": 0, "modelos": []})
        d["tokens"] += int(r["e"] + r["s"]); d["chamadas"] += int(r["n"]); d["estimadas"] += int(r["est"]); d["modelos"].append(r["modelo"])
    total = sum(d["tokens"] for d in por_esp.values())
    custo = config.get("custo", {})
    teto_t, teto_e = int(custo.get("teto_tokens_mes_total", 0) or 0), int(custo.get("teto_tokens_mes_por_especialista", 0) or 0)
    estourados = []
    if teto_t and total > teto_t:
        estourados.append(f"total {total} > {teto_t}")
    for e, d in por_esp.items():
        if teto_e and d["tokens"] > teto_e:
            estourados.append(f"{e} {d['tokens']} > {teto_e}")
    return {"mes": mes, "total_tokens": total, "por_especialista": por_esp, "teto_total": teto_t, "teto_por_especialista": teto_e,
            "estourados": estourados, "observacao": "provedor por assinatura (ChatGPT): sem valor em reais; tokens estimados quando estimadas>0"}


def tabela(r: dict) -> str:
    linhas = [f"Custo de API — {r['mes']} (tokens; teto total {r['teto_total'] or 'sem'}, por especialista {r['teto_por_especialista'] or 'sem'})",
              "| Especialista | Tokens | Chamadas | Estimadas |", "|---|---|---|---|"]
    for e, d in r["por_especialista"].items():
        linhas.append(f"| {e} | {d['tokens']} | {d['chamadas']} | {d['estimadas']} |")
    linhas.append(f"| **total** | {r['total_tokens']} | | |")
    if r["estourados"]:
        linhas.append("⚠️ Teto estourado: " + "; ".join(r["estourados"]))
    return "\n".join(linhas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mes", default=dt.date.today().strftime("%Y-%m"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--raiz", default=str(RAIZ))
    a = ap.parse_args()
    raiz = Path(a.raiz); config = carregar_config(raiz)
    con = db.inicializar(caminho_db(config, raiz))
    r = resumo(con, config, a.mes)
    print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else tabela(r))
    return 3 if r["estourados"] else 0


if __name__ == "__main__":
    sys.exit(main())
