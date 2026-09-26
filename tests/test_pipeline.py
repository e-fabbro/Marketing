import yaml

import pipeline
import transicao
from conftest import ARTE_OK, ARTE_RUIM, COMPLIANCE_LLM_OK, COPY_CURA, COPY_OK, FakeCliente
import render_arte
import pytest



PAUTA = """semana: "2026-09-28"
resumo: "teste"
pecas:
  - id: "2026-09-29_ansiedade"
    canal: instagram
    canal_conta: pessoal
    formato: carrossel
    pilar: 3
    persona: "Marina"
    tema: "Ansiedade"
    angulo: "explicar"
    objetivo: salvamentos
    cta: "Salve."
    atencao_compliance: ["assinatura"]
    horario: "18:30"
"""


def test_pauta_cria_pecas(con, raiz, config):
    cli = FakeCliente({"estrategista": [PAUTA]})
    p = pipeline.gerar_pauta("2026-09-28", raiz=raiz, con=con, cliente=cli, config=config, criar=True)
    assert p.exists()
    assert con.execute("SELECT estado FROM pecas WHERE id='2026-09-29_ansiedade'").fetchone()[0] == "PAUTA"
    dados = yaml.safe_load((raiz / "conteudo" / "2026-09-29_ansiedade" / "peca.yaml").read_text())
    assert dados["tema"] == "Ansiedade" and dados["historico"][0]["autor"] == "estrategista"


def _peca(con, raiz):
    if not (raiz / "templates").exists():
        (raiz / "templates").symlink_to(render_arte.RAIZ / "templates")
    transicao.criar_peca(con, raiz, id="2026-09-29_x", canal="instagram", formato="post", pilar="3",
                         objetivo="alcance", cta="salve", autor="estrategista")


def test_peca_limpa_chega_a_aguardando_humano(con, raiz, config):
    _peca(con, raiz)
    cli = FakeCliente({"redator": [COPY_OK], "designer": [ARTE_OK], "compliance": [COMPLIANCE_LLM_OK]})
    assert pipeline.processar_peca("2026-09-29_x", raiz=raiz, con=con, cliente=cli, config=config) == "AGUARDANDO_HUMANO"
    assert (raiz / "conteudo" / "2026-09-29_x" / "arte_01.png").exists()
    estados = [r[0] for r in con.execute("SELECT para FROM transicoes WHERE peca_id='2026-09-29_x' ORDER BY id")]
    assert estados == ["PAUTA", "RASCUNHO", "ARTE", "COMPLIANCE", "APROVADO_COMPLIANCE", "AGUARDANDO_HUMANO"]
    assert con.execute("SELECT count(*) FROM custos WHERE especialista='redator'").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM custos WHERE especialista='compliance'").fetchone()[0] == 1


def test_reprovada_volta_corrige_e_passa(con, raiz, config):
    _peca(con, raiz)
    cli = FakeCliente({"redator": [COPY_CURA, COPY_OK], "designer": [ARTE_OK], "compliance": [COMPLIANCE_LLM_OK]})
    assert pipeline.processar_peca("2026-09-29_x", raiz=raiz, con=con, cliente=cli, config=config) == "AGUARDANDO_HUMANO"
    estados = [r[0] for r in con.execute("SELECT para FROM transicoes WHERE peca_id='2026-09-29_x' ORDER BY id")]
    assert "REPROVADO" in estados and estados[-1] == "AGUARDANDO_HUMANO"
    assert con.execute("SELECT voltas_compliance FROM pecas").fetchone()[0] == 1


def test_tres_reprovacoes_escalam(con, raiz, config):
    _peca(con, raiz)
    cli = FakeCliente({"redator": [COPY_CURA], "designer": [ARTE_OK], "compliance": [COMPLIANCE_LLM_OK]})
    assert pipeline.processar_peca("2026-09-29_x", raiz=raiz, con=con, cliente=cli, config=config, cliente_compliance=None) == "ESCALAR"
    assert con.execute("SELECT voltas_compliance FROM pecas").fetchone()[0] == 3
    assert con.execute("SELECT count(*) FROM transicoes WHERE para='REPROVADO'").fetchone()[0] == 3


def test_teto_de_tokens_para_o_pipeline(con, raiz, config):
    _peca(con, raiz)
    config["custo"]["teto_tokens_mes_total"] = 100
    con.execute("INSERT INTO custos (especialista, modelo, tokens_entrada, tokens_saida) VALUES ('redator','m',90,20)")
    con.commit()
    cli = FakeCliente({"redator": [COPY_OK], "designer": [ARTE_OK], "compliance": [COMPLIANCE_LLM_OK]})
    with pytest.raises(RuntimeError, match="teto"):
        pipeline.processar_peca("2026-09-29_x", raiz=raiz, con=con, cliente=cli, config=config)


def test_arte_invalida_e_reenviada_ao_designer_e_depois_falha(con, raiz, config):
    _peca(con, raiz)
    cli = FakeCliente({"redator": [COPY_OK], "designer": [ARTE_RUIM, ARTE_OK], "compliance": [COMPLIANCE_LLM_OK]})
    assert pipeline.processar_peca("2026-09-29_x", raiz=raiz, con=con, cliente=cli, config=config) == "AGUARDANDO_HUMANO"
    assert [c[0] for c in cli.chamadas].count("designer") == 2
    transicao.criar_peca(con, raiz, id="2026-09-29_y", canal="instagram", formato="post", pilar="3", objetivo="alcance", cta="salve", autor="estrategista")
    cli = FakeCliente({"redator": [COPY_OK], "designer": [ARTE_RUIM], "compliance": [COMPLIANCE_LLM_OK]})
    with pytest.raises(render_arte.ArteInvalida):
        pipeline.processar_peca("2026-09-29_y", raiz=raiz, con=con, cliente=cli, config=config)
    assert con.execute("SELECT estado FROM pecas WHERE id='2026-09-29_y'").fetchone()[0] == "RASCUNHO"
