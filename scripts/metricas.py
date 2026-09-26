#!/usr/bin/env python3
"""Coleta determinística de métricas → tabela `metricas`; extrato para o ANALISTA; alertas de anomalia.

  metricas.py coletar  [--dias 7]                 Google Ads (todas as contas de config ou descobertas) → metricas
  metricas.py extrato  --de AAAA-MM-DD --ate AAAA-MM-DD [--md]   dados do período (JSON ou tabelas markdown)
  metricas.py anomalias [--data AAAA-MM-DD]        gasto acima do ritmo, CPC fora do padrão, anúncio reprovado
  metricas.py contas                                lista contas acessíveis (via ads_leitura) e grava proposta em dados/

Números só da API: nada aqui estima. Falha de coleta é registrada em logs/metricas.log e no retorno.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
from comum import RAIZ, agora_iso, caminho_db, carregar_config, carregar_env, logger  # noqa: E402

ADS_PYTHON_PADRAO = "/root/.hermes/profiles/duds/lib/google-ads-mcp/venv/bin/python"
METRICAS_CAMPANHA = ("custo", "cliques", "impressoes", "conversoes", "ctr", "cpc", "orcamento_diario")


def ads_python(raiz: Path) -> str:
    return carregar_env(raiz).get("AGENCIA_ADS_PYTHON") or ADS_PYTHON_PADRAO


def ads_comando(raiz: Path) -> list[str]:
    """Prefixo para rodar ads_leitura.py. O venv do MCP foi criado dentro do container (interpretador em
    /usr/local/bin); no host o link é quebrado, então cai para `docker exec` no container do DUDS."""
    import os
    py = ads_python(raiz)
    real = os.path.realpath(py)
    if os.path.exists(real) and os.access(real, os.X_OK):
        return [py]
    container = carregar_env(raiz).get("AGENCIA_DUDS_CONTAINER", "hermes-gateway-duds")
    return ["docker", "exec", container, py]


def ler_ads(args: list[str], raiz: Path) -> dict:
    """Chama ads_leitura.py com o Python do venv do MCP (local ou via docker exec); devolve o JSON."""
    cmd = [*ads_comando(raiz), str(raiz / "scripts" / "ads_leitura.py"), *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"ok": False, "erro": f"saída inválida ({r.returncode}): {r.stderr[-400:]}"}


def contas_configuradas(config: dict, raiz: Path) -> list[str]:
    ids = [str(c.get("customer_id", "")).replace("-", "") for c in config.get("google_ads", {}).get("contas", []) if c.get("customer_id")]
    if ids:
        return ids
    p = raiz / "dados" / "ads_contas.json"
    if p.exists():
        return [c["customer_id"] for c in json.loads(p.read_text(encoding="utf-8")) if not c.get("mcc") and "erro" not in c]
    return []


def gravar_campanhas(con, linhas: list[dict], coletado_em: str) -> int:
    """INSERT OR REPLACE na chave (fonte, entidade_id, data, metrica). Guarda nomes em dados/ads_entidades.json."""
    n = 0
    for l in linhas:
        ent = f"campanha:{l['campanha_id']}"
        for m in METRICAS_CAMPANHA:
            con.execute("INSERT OR REPLACE INTO metricas (fonte, entidade_id, data, metrica, valor, coletado_em) VALUES ('google_ads',?,?,?,?,?)",
                        (ent, l["data"], m, float(l[m]), coletado_em))
            n += 1
    con.commit()
    return n


def atualizar_entidades(raiz: Path, linhas: list[dict], conta: str) -> None:
    p = raiz / "dados" / "ads_entidades.json"
    ent = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    for l in linhas:
        ent[f"campanha:{l['campanha_id']}"] = {"nome": l["campanha"], "conta": conta, "status": l["status"]}
    p.write_text(json.dumps(ent, ensure_ascii=False, indent=1), encoding="utf-8")


def coletar(*, raiz: Path, con, config: dict, dias: int, leitor=None) -> dict:
    """leitor(args) → dict; padrão = ler_ads (subprocess). Devolve resumo por conta."""
    log = logger("metricas", raiz)
    leitor = leitor or (lambda args: ler_ads(args, raiz))
    resumo = {"contas": {}, "coletado_em": agora_iso()}
    contas = contas_configuradas(config, raiz)
    if not contas:
        resumo["erro"] = "nenhuma conta: rode `metricas.py contas` ou preencha config google_ads.contas"
        log.error(resumo["erro"])
        return resumo
    for conta in contas:
        r = leitor(["campanhas", "--conta", conta, "--dias", str(dias)])
        if not r.get("ok"):
            resumo["contas"][conta] = {"erro": r.get("erro")}
            log.error("conta %s: %s", conta, r.get("erro"))
            continue
        n = gravar_campanhas(con, r["dados"], r["coletado_em"])
        atualizar_entidades(raiz, r["dados"], conta)
        rep = leitor(["reprovados", "--conta", conta])
        reprov = rep.get("dados", []) if rep.get("ok") else []
        (raiz / "dados" / f"ads_reprovados_{conta}.json").write_text(json.dumps({"coletado_em": r["coletado_em"], "dados": reprov}, ensure_ascii=False, indent=1), encoding="utf-8")
        resumo["contas"][conta] = {"linhas": len(r["dados"]), "metricas_gravadas": n, "reprovados": len(reprov)}
        log.info("conta %s: %d linhas, %d métricas, %d reprovados", conta, len(r["dados"]), n, len(reprov))
    return resumo


def extrato(con, de: str, ate: str, raiz: Path) -> dict:
    rows = con.execute("SELECT fonte, entidade_id, data, metrica, valor, coletado_em FROM metricas WHERE data BETWEEN ? AND ? ORDER BY entidade_id, data, metrica", (de, ate)).fetchall()
    p = raiz / "dados" / "ads_entidades.json"
    nomes = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    por_ent: dict[str, dict] = {}
    coletas = set()
    for r in rows:
        e = por_ent.setdefault(r["entidade_id"], {"fonte": r["fonte"], "nome": nomes.get(r["entidade_id"], {}).get("nome", r["entidade_id"]), "dias": {}})
        e["dias"].setdefault(r["data"], {})[r["metrica"]] = r["valor"]
        coletas.add(r["coletado_em"])
    totais = {}
    for ent, e in por_ent.items():
        t = {"custo": 0.0, "cliques": 0, "impressoes": 0, "conversoes": 0.0, "dias_com_dado": len(e["dias"])}
        for d in e["dias"].values():
            t["custo"] += d.get("custo", 0.0); t["cliques"] += int(d.get("cliques", 0)); t["impressoes"] += int(d.get("impressoes", 0)); t["conversoes"] += d.get("conversoes", 0.0)
        t["custo"] = round(t["custo"], 2); t["conversoes"] = round(t["conversoes"], 2)
        t["cpc"] = round(t["custo"] / t["cliques"], 2) if t["cliques"] else None
        t["cpa"] = round(t["custo"] / t["conversoes"], 2) if t["conversoes"] else None
        totais[ent] = {"nome": e["nome"], **t}
    return {"de": de, "ate": ate, "fontes": sorted({e["fonte"] for e in por_ent.values()}), "coletas": sorted(coletas), "entidades": por_ent, "totais": totais}


def extrato_md(ex: dict) -> str:
    if not ex["totais"]:
        return f"Sem dados coletados para o período {ex['de']} a {ex['ate']}."
    linhas = [f"Período {ex['de']} a {ex['ate']} · fontes: {', '.join(ex['fontes'])} · coletas: {', '.join(ex['coletas'][-3:])}", "",
              "| Campanha | Custo | Cliques | CPC | Impressões | Conversões | CPA | Dias com dado |", "|---|---|---|---|---|---|---|---|"]
    for ent, t in ex["totais"].items():
        linhas.append(f"| {t['nome']} | {t['custo']:.2f} | {t['cliques']} | {t['cpc'] if t['cpc'] is not None else '-'} | {t['impressoes']} | {t['conversoes']:.2f} | {t['cpa'] if t['cpa'] is not None else '-'} | {t['dias_com_dado']} |")
    return "\n".join(linhas)


def anomalias(con, raiz: Path, data: str | None = None, janela: int = 28, sigmas: float = 2.0) -> list[dict]:
    """Determinístico: custo e cpc do dia vs média ± sigmas·desvio dos `janela` dias anteriores; ritmo vs orçamento; reprovados."""
    dia = data or (dt.date.today() - dt.timedelta(days=1)).isoformat()
    ini = (dt.date.fromisoformat(dia) - dt.timedelta(days=janela)).isoformat()
    p = raiz / "dados" / "ads_entidades.json"
    nomes = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    alertas = []
    ents = [r[0] for r in con.execute("SELECT DISTINCT entidade_id FROM metricas WHERE fonte='google_ads' AND data=?", (dia,))]
    for ent in ents:
        nome = nomes.get(ent, {}).get("nome", ent)
        hoje = {r["metrica"]: r["valor"] for r in con.execute("SELECT metrica, valor FROM metricas WHERE entidade_id=? AND data=?", (ent, dia))}
        for m in ("custo", "cpc"):
            hist = [r[0] for r in con.execute("SELECT valor FROM metricas WHERE entidade_id=? AND metrica=? AND data>=? AND data<? AND valor>0", (ent, m, ini, dia))]
            if len(hist) >= 5 and m in hoje:
                med, dp = statistics.mean(hist), statistics.pstdev(hist)
                faixa = (round(med - sigmas * dp, 2), round(med + sigmas * dp, 2))
                if hoje[m] > faixa[1] or (hoje[m] < faixa[0] and hoje[m] > 0):
                    alertas.append({"tipo": f"{m}_fora_do_padrao", "campanha": nome, "data": dia, "valor": hoje[m], "faixa": faixa, "amostra": len(hist), "fonte": "google_ads"})
        orc = hoje.get("orcamento_diario", 0)
        if orc and hoje.get("custo", 0) > 1.5 * orc:
            alertas.append({"tipo": "gasto_acima_do_ritmo", "campanha": nome, "data": dia, "valor": hoje["custo"], "orcamento_diario": orc, "fonte": "google_ads"})
    for f in (raiz / "dados").glob("ads_reprovados_*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        for a in d.get("dados", []):
            alertas.append({"tipo": "anuncio_reprovado", "campanha": a["campanha"], "grupo": a["grupo"], "anuncio_id": a["anuncio_id"], "topicos": a["topicos"], "coletado_em": d["coletado_em"], "fonte": "google_ads"})
    return alertas


def alertas_md(alertas: list[dict], dia: str) -> str:
    if not alertas:
        return f"Sem anomalias em {dia}."
    linhas = [f"⚠️ Alertas Google Ads — {dia}"]
    for a in alertas:
        if a["tipo"] == "anuncio_reprovado":
            linhas.append(f"- Anúncio reprovado: {a['campanha']} / {a['grupo']} (id {a['anuncio_id']}): {', '.join(a['topicos']) or 'ver conta'}")
        elif a["tipo"] == "gasto_acima_do_ritmo":
            linhas.append(f"- Gasto acima do ritmo: {a['campanha']} gastou {a['valor']:.2f} com orçamento diário {a['orcamento_diario']:.2f}")
        else:
            linhas.append(f"- {a['tipo'].replace('_', ' ')}: {a['campanha']} = {a['valor']:.2f} (faixa {a['faixa'][0]}–{a['faixa'][1]}, {a['amostra']} dias)")
    linhas.append("Nenhuma ação foi executada; propostas exigem aprovação.")
    return "\n".join(linhas)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raiz", default=str(RAIZ))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("coletar"); s.add_argument("--dias", type=int, default=7)
    s = sub.add_parser("extrato"); s.add_argument("--de", required=True); s.add_argument("--ate", required=True); s.add_argument("--md", action="store_true")
    s = sub.add_parser("anomalias"); s.add_argument("--data")
    sub.add_parser("contas")
    a = ap.parse_args(argv)
    raiz = Path(a.raiz)
    config = carregar_config(raiz)
    con = db.inicializar(caminho_db(config, raiz))
    if a.cmd == "contas":
        r = ler_ads(["contas"], raiz)
        if r.get("ok"):
            (raiz / "dados" / "ads_contas.json").write_text(json.dumps(r["dados"], ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r.get("ok") else 1
    if a.cmd == "coletar":
        r = coletar(raiz=raiz, con=con, config=config, dias=a.dias)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if "erro" not in r else 1
    if a.cmd == "extrato":
        ex = extrato(con, a.de, a.ate, raiz)
        print(extrato_md(ex) if a.md else json.dumps(ex, ensure_ascii=False, indent=1))
        return 0
    al = anomalias(con, raiz, a.data)
    dia = a.data or (dt.date.today() - dt.timedelta(days=1)).isoformat()
    (raiz / "relatorios" / f"alertas_{dia}.md").write_text(alertas_md(al, dia) + "\n", encoding="utf-8")
    print(alertas_md(al, dia))
    return 0


if __name__ == "__main__":
    sys.exit(main())
