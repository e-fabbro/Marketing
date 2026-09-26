#!/usr/bin/env python3
"""Leitura do Google Ads (somente leitura), com as MESMAS credenciais e o mesmo venv do MCP google-ads do
DUDS. Nunca escreve na conta. Saída sempre em JSON no stdout.

Rodar com o Python do venv do MCP (tem a biblioteca google-ads):
  /root/.hermes/profiles/duds/lib/google-ads-mcp/venv/bin/python scripts/ads_leitura.py contas
  ... campanhas --conta 1234567890 --dias 7
  ... reprovados --conta 1234567890

Credenciais (como em bin/google-ads-mcp-bridge.py): <perfil>/secrets/google-ads/credentials.json
(authorized_user) e <perfil>/secrets/google-ads/env.sh (DUDS_GOOGLE_ADS_DEVELOPER_TOKEN,
DUDS_GOOGLE_ADS_LOGIN_CUSTOMER_ID opcionais). Nada disso é impresso.
Sem dependência de PyYAML: só stdlib + google-ads.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

PERFIL = Path(os.environ.get("AGENCIA_PERFIL_DUDS", "/root/.hermes/profiles/duds"))
SECRETS = PERFIL / "secrets" / "google-ads"


def _env_secrets() -> dict:
    env = {}
    f = SECRETS / "env.sh"
    if f.exists():
        for line in f.read_text().splitlines():
            m = re.match(r"\s*(?:export\s+)?(DUDS_GOOGLE_ADS_[A-Z_]+)=(.*)$", line)
            if m:
                env[m.group(1)] = m.group(2).strip().strip("'\"")
    return env


def cliente():
    """GoogleAdsClient com credenciais authorized_user do arquivo do perfil."""
    from google.ads.googleads.client import GoogleAdsClient
    from google.oauth2.credentials import Credentials
    cred_file = SECRETS / "credentials.json"
    if not cred_file.exists():
        raise SystemExit(f"credenciais ausentes: {cred_file}")
    creds = Credentials.from_authorized_user_file(str(cred_file))
    env = _env_secrets()
    # Desde 2026-09-09 o controle de acesso é do projeto Cloud; a biblioteca ainda exige valor não vazio.
    dev = env.get("DUDS_GOOGLE_ADS_DEVELOPER_TOKEN") or os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN") or "unused"
    login = re.sub(r"\D", "", env.get("DUDS_GOOGLE_ADS_LOGIN_CUSTOMER_ID", "")) or None
    kwargs = {"credentials": creds, "developer_token": dev, "use_proto_plus": True}
    if login:
        kwargs["login_customer_id"] = login
    return GoogleAdsClient(**kwargs)


def _stream(cli, conta: str, gaql: str):
    svc = cli.get_service("GoogleAdsService")
    for lote in svc.search_stream(customer_id=re.sub(r"\D", "", conta), query=gaql):
        for row in lote.results:
            yield row


def contas(cli) -> list[dict]:
    svc = cli.get_service("CustomerService")
    saida = []
    for rn in svc.list_accessible_customers().resource_names:
        cid = rn.split("/")[-1]
        try:
            row = next(_stream(cli, cid, "SELECT customer.id, customer.descriptive_name, customer.currency_code, customer.time_zone, customer.manager FROM customer LIMIT 1"))
            saida.append({"customer_id": cid, "nome": row.customer.descriptive_name, "moeda": row.customer.currency_code,
                          "fuso": row.customer.time_zone, "mcc": bool(row.customer.manager)})
        except Exception as exc:  # noqa: BLE001 — conta inacessível: registrar e seguir
            saida.append({"customer_id": cid, "erro": str(exc)[:200]})
    return saida


def campanhas(cli, conta: str, dias: int) -> list[dict]:
    fim = dt.date.today() - dt.timedelta(days=1)
    ini = fim - dt.timedelta(days=dias - 1)
    gaql = f"""
      SELECT campaign.id, campaign.name, campaign.status, campaign_budget.amount_micros, segments.date,
             metrics.cost_micros, metrics.clicks, metrics.impressions, metrics.conversions, metrics.ctr, metrics.average_cpc
      FROM campaign
      WHERE segments.date BETWEEN '{ini:%Y-%m-%d}' AND '{fim:%Y-%m-%d}' AND campaign.status != 'REMOVED'
      ORDER BY segments.date"""
    saida = []
    for r in _stream(cli, conta, gaql):
        saida.append(linha_campanha(r.campaign.id, r.campaign.name, r.campaign.status.name, r.campaign_budget.amount_micros,
                                    r.segments.date, r.metrics.cost_micros, r.metrics.clicks, r.metrics.impressions,
                                    r.metrics.conversions, r.metrics.ctr, r.metrics.average_cpc))
    return saida


def linha_campanha(cid, nome, status, orcamento_micros, data, custo_micros, cliques, impressoes, conversoes, ctr, cpc_micros) -> dict:
    """Normalização pura (testável sem a API): micros → unidades da moeda."""
    return {"campanha_id": str(cid), "campanha": nome, "status": status, "orcamento_diario": round(orcamento_micros / 1e6, 2),
            "data": str(data), "custo": round(custo_micros / 1e6, 2), "cliques": int(cliques), "impressoes": int(impressoes),
            "conversoes": float(conversoes), "ctr": round(float(ctr), 4), "cpc": round(cpc_micros / 1e6, 2)}


def reprovados(cli, conta: str) -> list[dict]:
    gaql = """
      SELECT campaign.name, ad_group.name, ad_group_ad.ad.id, ad_group_ad.policy_summary.approval_status,
             ad_group_ad.policy_summary.policy_topic_entries
      FROM ad_group_ad
      WHERE ad_group_ad.policy_summary.approval_status IN ('DISAPPROVED', 'AREA_OF_INTEREST_ONLY')
        AND ad_group_ad.status != 'REMOVED'"""
    saida = []
    for r in _stream(cli, conta, gaql):
        topicos = [getattr(t, "topic", "") for t in r.ad_group_ad.policy_summary.policy_topic_entries]
        saida.append({"campanha": r.campaign.name, "grupo": r.ad_group.name, "anuncio_id": str(r.ad_group_ad.ad.id),
                      "status": r.ad_group_ad.policy_summary.approval_status.name, "topicos": topicos})
    return saida


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("contas")
    c = sub.add_parser("campanhas"); c.add_argument("--conta", required=True); c.add_argument("--dias", type=int, default=7)
    r = sub.add_parser("reprovados"); r.add_argument("--conta", required=True)
    a = ap.parse_args(argv)
    try:
        cli = cliente()
        if a.cmd == "contas":
            dados = contas(cli)
        elif a.cmd == "campanhas":
            dados = campanhas(cli, a.conta, a.dias)
        else:
            dados = reprovados(cli, a.conta)
        print(json.dumps({"ok": True, "coletado_em": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "fonte": "google_ads", "dados": dados}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001
        msg = re.sub(r"(ya29\.[\w-]+|1//[\w-]+)", "<token>", str(exc))
        print(json.dumps({"ok": False, "erro": msg[:800]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
