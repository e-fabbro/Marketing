import datetime as dt
import json

import pytest

import metricas
import relatorio
from test_metricas import _leitor, _linhas


def _dados(con, raiz, config):
    config["google_ads"] = {"contas": [{"customer_id": "1"}]}
    # semana anterior: custo 10/dia; semana alvo (21 a 27/09): custo 20/dia
    ant = _linhas(7, custo=10.0, fim=dt.date(2026, 9, 20))
    atual = _linhas(7, custo=20.0, fim=dt.date(2026, 9, 27))
    metricas.coletar(raiz=raiz, con=con, config=config, dias=14, leitor=_leitor(ant + atual))


def test_preparar_gera_prompt_com_tabelas(con, raiz, config):
    _dados(con, raiz, config)
    r = relatorio.preparar("semanal", raiz=raiz, con=con, config=config, semana="2026-09-21")
    assert r["acao"] == "delegar" and r["especialista"] == "analista" and r["id"] == "semanal_2026-09-21"
    txt = open(r["prompt"], encoding="utf-8").read()
    assert "| Busca DF | 140.00 | 70 |" in txt and "name: agencia-analista" in txt and "REGRA: use SOMENTE" in txt
    assert (raiz / "relatorios" / "semanal_2026-09-21.pendente.json").exists()


def test_entregar_aceita_numeros_dos_dados_e_variacao(con, raiz, config):
    _dados(con, raiz, config)
    relatorio.preparar("semanal", raiz=raiz, con=con, config=config, semana="2026-09-21")
    texto = "```\n# Relatório semanal\nCusto 140.00 (fonte: google_ads) vs 70.00 na anterior (+100%). Cliques: 70. CPC 1.0.\n## Resumo em 3 linhas\nok\n```"
    r = relatorio.entregar("semanal_2026-09-21", texto, raiz=raiz, con=con, config=config)
    assert r["acao"] == "fim"
    conteudo = (raiz / "relatorios" / "semanal_2026-09-21.md").read_text(encoding="utf-8")
    assert conteudo.startswith("<!-- gerado") and "Custo 140.00" in conteudo
    assert con.execute("SELECT especialista, estimado FROM custos").fetchone()[:] == ("analista", 1)


def test_entregar_rejeita_numero_inventado(con, raiz, config):
    _dados(con, raiz, config)
    relatorio.preparar("semanal", raiz=raiz, con=con, config=config, semana="2026-09-21")
    with pytest.raises(RuntimeError, match="15000.00"):
        relatorio.entregar("semanal_2026-09-21", "```\nAlcance estimado de 15.000 pessoas. Custo 140.00.\n```", raiz=raiz, con=con, config=config)
    assert (raiz / "relatorios" / "semanal_2026-09-21.pendente.json").exists()      # continua pendente


def test_numeros_texto_ignora_datas_ids_e_contagens_pequenas():
    n = relatorio._numeros_texto("Em 2026-09-21T10:00:00Z, 3 linhas, id 123456789, custo R$ 1.234,50, CTR 2,5%, cliques 70, alcance 15.000")
    assert n == {"1234.50", "2.50", "70.00", "15000.00"}


def test_trafego_prepara_proposta(con, raiz, config):
    _dados(con, raiz, config)
    r = relatorio.preparar("trafego", raiz=raiz, con=con, config=config, dias=7)
    assert r["especialista"] == "trafego" and r["id"].startswith("trafego_")
