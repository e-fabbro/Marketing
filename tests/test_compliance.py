import json

import pytest

import compliance
import compliance_regras
import transicao
from conftest import COPY_CURA, COPY_OK, COPY_SEM_CRM, FakeCliente


def _peca(con, raiz, copy, pid="2026-09-29_teste"):
    transicao.criar_peca(con, raiz, id=pid, canal="instagram", formato="post", pilar="3",
                         objetivo="alcance", cta="salve", autor="estrategista")
    (raiz / "conteudo" / pid / "copy.md").write_text(copy, encoding="utf-8")
    return pid


def test_cura_garantida_em_30_dias_e_reprovada(con, raiz):
    pid = _peca(con, raiz, COPY_CURA)
    r = compliance.avaliar_peca(pid, raiz=raiz, con=con, cliente=None)
    assert r["resultado"] == "REPROVADO"
    assert any("cura" in t.lower() for t in r["trechos_problematicos"])
    item2 = next(i for i in r["itens"] if i["n"] == 2)
    assert item2["status"] == "falha"
    assert json.loads((raiz / "conteudo" / pid / "compliance.json").read_text())["resultado"] == "REPROVADO"


def test_sem_crm_rqe_e_reprovada(con, raiz):
    pid = _peca(con, raiz, COPY_SEM_CRM)
    r = compliance.avaliar_peca(pid, raiz=raiz, con=con, cliente=None)
    assert r["resultado"] == "REPROVADO"
    assert next(i for i in r["itens"] if i["n"] == 1)["status"] == "falha"


def test_peca_limpa_passa_nas_regras(con, raiz):
    pid = _peca(con, raiz, COPY_OK)
    r = compliance.avaliar_peca(pid, raiz=raiz, con=con, cliente=None)
    assert r["resultado"] == "APROVADO_COMPLIANCE"
    assert len(r["itens"]) == 8


def test_assinatura_com_todo_reprova(con, raiz):
    pid = _peca(con, raiz, COPY_OK.replace("CRM-DF 27043", "CRM-TODO 27043"))
    assert compliance.avaliar_peca(pid, raiz=raiz, con=con, cliente=None)["resultado"] == "REPROVADO"


def test_preco_escala(con, raiz):
    pid = _peca(con, raiz, COPY_OK.replace("Salve para reler.", "Consulta por R$ 300 este mês."))
    r = compliance.avaliar_peca(pid, raiz=raiz, con=con, cliente=None)
    assert r["resultado"] == "ESCALAR" and "preço" in r["motivo_escalar"]


def test_depoimento_nunca_e_ok(con, raiz):
    pid = _peca(con, raiz, COPY_OK.replace("Cada caso é individual.", "Veja o depoimento da minha paciente."))
    r = compliance.avaliar_peca(pid, raiz=raiz, con=con, cliente=None)
    assert r["resultado"] == "REPROVADO"


def test_suicidio_sem_cvv_reprova_e_com_cvv_passa(con, raiz):
    base = COPY_OK.replace("Cada caso é individual.", "Pensamentos de suicídio pedem ajuda imediata.")
    assert compliance.avaliar_peca(_peca(con, raiz, base, "2026-09-29_a"), raiz=raiz, con=con, cliente=None)["resultado"] == "REPROVADO"
    com_cvv = base.replace("ajuda imediata.", "ajuda imediata. Ligue 188 (CVV).")
    assert compliance.avaliar_peca(_peca(con, raiz, com_cvv, "2026-09-29_b"), raiz=raiz, con=con, cliente=None)["resultado"] == "APROVADO_COMPLIANCE"


def test_norma_ausente_escala(con, raiz):
    (raiz / "brand" / "normas" / "cfm-2336-2023.md").unlink()
    pid = _peca(con, raiz, COPY_OK)
    r = compliance.avaliar_peca(pid, raiz=raiz, con=con, cliente=None)
    assert r["resultado"] == "ESCALAR" and "norma ausente" in r["motivo_escalar"]


def test_llm_nao_reverte_falha_das_regras(con, raiz):
    pid = _peca(con, raiz, COPY_CURA)
    cli = FakeCliente({"compliance": ['{"resultado": "APROVADO_COMPLIANCE", "itens": [], "trechos_problematicos": []}']})
    r = compliance.avaliar_peca(pid, raiz=raiz, con=con, cliente=cli)
    assert r["resultado"] == "REPROVADO" and r["camadas"] == ["regras", "llm"]
    assert cli.chamadas[0][2] == 0.0          # temperatura baixa do compliance


def test_llm_pode_endurecer(con, raiz):
    pid = _peca(con, raiz, COPY_OK)
    cli = FakeCliente({"compliance": ['{"resultado": "REPROVADO", "itens": [], "trechos_problematicos": ["tom alarmista"], "recomendacao_ao_redator": "suavize"}']})
    r = compliance.avaliar_peca(pid, raiz=raiz, con=con, cliente=cli)
    assert r["resultado"] == "REPROVADO" and "tom alarmista" in r["trechos_problematicos"]


def test_termos_vetados_vem_do_proibidos(raiz):
    termos = compliance_regras.carregar_termos_vetados(raiz / "brand")
    assert "cura" in termos and "melhor" in termos and "garantia" in termos and "promoção" not in termos


def test_termo_vetado_casa_por_palavra_inteira():
    assert not compliance_regras.termo_presente("cura", compliance_regras._norm("Ansiedade não é frescura."))
    assert compliance_regras.termo_presente("cura", compliance_regras._norm("Prometo a CURA."))
    assert compliance_regras.termo_presente("100%", compliance_regras._norm("eficácia de 100% comprovada"))


def test_llm_com_trechos_em_objeto_json_nao_quebra(con, raiz, config):
    """Regressão do bug achado na VPS: trechos_problematicos como dicts."""
    import pipeline, transicao as t
    pid = _peca(con, raiz, COPY_OK)
    cli = FakeCliente({"compliance": ['{"resultado": "REPROVADO", "itens": [], "trechos_problematicos": [{"trecho": "tom alarmista", "item": 8}, {"x": 1}, "tom alarmista"], "recomendacao_ao_redator": "suavize"}']})
    r = compliance.avaliar_peca(pid, raiz=raiz, con=con, cliente=cli)
    assert r["trechos_problematicos"] == ["tom alarmista", '{"x": 1}']
    # e o motivo da transição (join dos trechos) também funciona
    for para, autor in [("RASCUNHO", "duds"), ("ARTE", "designer"), ("COMPLIANCE", "duds")]:
        t.mover(con, raiz, pid, para, autor, config=config)
    t.mover(con, raiz, pid, r["resultado"], "compliance", "; ".join(r["trechos_problematicos"]), config)
