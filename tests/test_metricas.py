import datetime as dt
import json

import ads_leitura
import metricas


def test_linha_campanha_converte_micros():
    l = ads_leitura.linha_campanha(1, "Busca", "ENABLED", 50_000_000, "2026-09-20", 12_345_678, 10, 1000, 2.0, 0.01, 1_234_567)
    assert l == {"campanha_id": "1", "campanha": "Busca", "status": "ENABLED", "orcamento_diario": 50.0, "data": "2026-09-20",
                 "custo": 12.35, "cliques": 10, "impressoes": 1000, "conversoes": 2.0, "ctr": 0.01, "cpc": 1.23}


def _linhas(dias, custo=10.0, cpc=1.0, orc=20.0, fim=None):
    fim = fim or dt.date(2026, 9, 25)
    out = []
    for i in range(dias):
        d = (fim - dt.timedelta(days=dias - 1 - i)).isoformat()
        out.append(ads_leitura.linha_campanha(7, "Busca DF", "ENABLED", int(orc * 1e6), d, int(custo * 1e6), 10, 500, 1.0, 0.02, int(cpc * 1e6)))
    return out


def _leitor(linhas, reprov=None):
    def f(args):
        if args[0] == "campanhas":
            return {"ok": True, "coletado_em": "2026-09-26T10:00:00Z", "dados": linhas}
        if args[0] == "reprovados":
            return {"ok": True, "coletado_em": "2026-09-26T10:00:00Z", "dados": reprov or []}
        return {"ok": False, "erro": "?"}
    return f


def test_coletar_grava_e_e_idempotente(con, raiz, config):
    config["google_ads"] = {"contas": [{"customer_id": "123-456-7890"}]}
    r = metricas.coletar(raiz=raiz, con=con, config=config, dias=3, leitor=_leitor(_linhas(3)))
    assert r["contas"]["1234567890"]["metricas_gravadas"] == 3 * len(metricas.METRICAS_CAMPANHA)
    n1 = con.execute("SELECT count(*) FROM metricas").fetchone()[0]
    metricas.coletar(raiz=raiz, con=con, config=config, dias=3, leitor=_leitor(_linhas(3)))
    assert con.execute("SELECT count(*) FROM metricas").fetchone()[0] == n1
    assert json.loads((raiz / "dados" / "ads_entidades.json").read_text())["campanha:7"]["nome"] == "Busca DF"


def test_coletar_sem_conta_reporta_erro(con, raiz, config):
    config["google_ads"] = {"contas": []}
    r = metricas.coletar(raiz=raiz, con=con, config=config, dias=3, leitor=_leitor([]))
    assert "erro" in r


def test_coletar_falha_da_api_e_registrada_nao_estimada(con, raiz, config):
    config["google_ads"] = {"contas": [{"customer_id": "1"}]}
    r = metricas.coletar(raiz=raiz, con=con, config=config, dias=3, leitor=lambda a: {"ok": False, "erro": "quota"})
    assert r["contas"]["1"]["erro"] == "quota"
    assert con.execute("SELECT count(*) FROM metricas").fetchone()[0] == 0


def test_extrato_totais_e_markdown(con, raiz, config):
    config["google_ads"] = {"contas": [{"customer_id": "1"}]}
    metricas.coletar(raiz=raiz, con=con, config=config, dias=7, leitor=_leitor(_linhas(7)))
    ex = metricas.extrato(con, "2026-09-19", "2026-09-25", raiz)
    t = ex["totais"]["campanha:7"]
    assert t["custo"] == 70.0 and t["cliques"] == 70 and t["cpc"] == 1.0 and t["dias_com_dado"] == 7 and t["cpa"] == 10.0
    md = metricas.extrato_md(ex)
    assert "| Busca DF | 70.00 | 70 | 1.0 |" in md
    assert "Sem dados coletados" in metricas.extrato_md(metricas.extrato(con, "2020-01-01", "2020-01-07", raiz))


def test_anomalias_custo_cpc_ritmo_e_reprovados(con, raiz, config):
    config["google_ads"] = {"contas": [{"customer_id": "1"}]}
    hist = _linhas(10, custo=10.0, cpc=1.0, fim=dt.date(2026, 9, 24))
    ontem = _linhas(1, custo=45.0, cpc=3.0, orc=20.0, fim=dt.date(2026, 9, 25))
    reprov = [{"campanha": "Busca DF", "grupo": "G1", "anuncio_id": "99", "status": "DISAPPROVED", "topicos": ["HEALTH_IN_PERSONALIZED_ADS"]}]
    metricas.coletar(raiz=raiz, con=con, config=config, dias=11, leitor=_leitor(hist + ontem, reprov))
    al = metricas.anomalias(con, raiz, "2026-09-25")
    tipos = sorted(a["tipo"] for a in al)
    assert tipos == ["anuncio_reprovado", "cpc_fora_do_padrao", "custo_fora_do_padrao", "gasto_acima_do_ritmo"]
    md = metricas.alertas_md(al, "2026-09-25")
    assert "Anúncio reprovado" in md and "Nenhuma ação foi executada" in md
    assert metricas.alertas_md([], "x").startswith("Sem anomalias")


def test_anomalias_sem_historico_suficiente_nao_alarma(con, raiz, config):
    config["google_ads"] = {"contas": [{"customer_id": "1"}]}
    metricas.coletar(raiz=raiz, con=con, config=config, dias=3, leitor=_leitor(_linhas(3, custo=100.0, orc=200.0)))
    assert metricas.anomalias(con, raiz, "2026-09-25") == []


def test_ads_comando_cai_para_docker_quando_venv_quebrado(raiz, monkeypatch):
    (raiz / ".env").write_text("AGENCIA_ADS_PYTHON=/nao/existe/python\n", encoding="utf-8")
    assert metricas.ads_comando(raiz) == ["docker", "exec", "hermes-gateway-duds", "/nao/existe/python"]
    import sys
    (raiz / ".env").write_text(f"AGENCIA_ADS_PYTHON={sys.executable}\n", encoding="utf-8")
    assert metricas.ads_comando(raiz) == [sys.executable]


def test_formatar_erro_mascara_token_e_compacta():
    m = ads_leitura.formatar_erro(RuntimeError("falha ya29.abcDEF-123 e   1//xyz_9 aqui\n\n muito"))
    assert "ya29" not in m and "1//" not in m and "\n" not in m
