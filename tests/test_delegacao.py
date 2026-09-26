"""Modo delegação: o DUDS chama `passo`, delega, e devolve com `entregar`. Aqui o DUDS é simulado."""
import json

import pytest

import pipeline
import render_arte
import transicao
from conftest import ARTE_OK, ARTE_RUIM, COMPLIANCE_LLM_OK, COPY_CURA, COPY_OK


def _peca(con, raiz, pid="2026-09-29_d"):
    if not (raiz / "templates").exists():
        (raiz / "templates").symlink_to(render_arte.RAIZ / "templates")
    transicao.criar_peca(con, raiz, id=pid, canal="instagram", formato="post", pilar="3", objetivo="alcance", cta="salve", autor="estrategista")
    return pid


def _entrega(pid, texto, raiz, con, config):
    return pipeline.entregar_resposta(pid, f"```\n{texto}\n```", raiz=raiz, con=con, config=config)


def test_fluxo_completo_por_delegacao(con, raiz, config):
    pid = _peca(con, raiz)
    r = pipeline.proximo_passo(pid, raiz=raiz, con=con, config=config)
    assert r["acao"] == "delegar" and r["especialista"] == "redator"
    assert (raiz / "conteudo" / pid / "prompt_redator.md").exists()
    assert "name: agencia-redator" in open(r["prompt"], encoding="utf-8").read()
    # chamar passo de novo não avança nem duplica: repete a mesma delegação
    r2 = pipeline.proximo_passo(pid, raiz=raiz, con=con, config=config)
    assert r2["especialista"] == "redator" and "pendente" in r2["instrucao"]
    r = _entrega(pid, COPY_OK, raiz, con, config)
    assert r["especialista"] == "designer"
    r = _entrega(pid, ARTE_OK, raiz, con, config)
    assert r["especialista"] == "compliance" and r["modelo"] == config["especialistas"]["compliance"]["modelo"]
    assert (raiz / "conteudo" / pid / "arte_01.png").exists()
    assert con.execute("SELECT estado FROM pecas WHERE id=?", (pid,)).fetchone()[0] == "COMPLIANCE"
    r = _entrega(pid, COMPLIANCE_LLM_OK, raiz, con, config)
    assert r == {"acao": "fim", "estado": "AGUARDANDO_HUMANO", "detalhe": "o bot de aprovação envia ao grupo"}
    estados = [x[0] for x in con.execute("SELECT para FROM transicoes WHERE peca_id=? ORDER BY id", (pid,))]
    assert estados == ["PAUTA", "RASCUNHO", "ARTE", "COMPLIANCE", "APROVADO_COMPLIANCE", "AGUARDANDO_HUMANO"]
    custos = con.execute("SELECT especialista, estimado FROM custos ORDER BY id").fetchall()
    assert [(c[0], c[1]) for c in custos] == [("redator", 1), ("designer", 1), ("compliance", 1)]


def test_entregar_sem_pendencia_e_erro(con, raiz, config):
    pid = _peca(con, raiz)
    with pytest.raises(RuntimeError, match="nenhuma delegação pendente"):
        _entrega(pid, COPY_OK, raiz, con, config)


def test_resposta_invalida_mantem_pendente(con, raiz, config):
    pid = _peca(con, raiz)
    pipeline.proximo_passo(pid, raiz=raiz, con=con, config=config)
    _entrega(pid, COPY_OK, raiz, con, config)                       # agora pendente = designer (yaml)
    with pytest.raises(RuntimeError, match="inválida"):
        _entrega(pid, "template: [isto: não é yaml", raiz, con, config)
    et = json.loads((raiz / "conteudo" / pid / "etapas.json").read_text())
    assert et["pendente"]["especialista"] == "designer"


def test_arte_invalida_volta_ao_designer_com_o_erro(con, raiz, config):
    pid = _peca(con, raiz)
    pipeline.proximo_passo(pid, raiz=raiz, con=con, config=config)
    _entrega(pid, COPY_OK, raiz, con, config)
    r = _entrega(pid, ARTE_RUIM, raiz, con, config)
    assert r["especialista"] == "designer"
    assert "ERRO na tentativa anterior" in open(r["prompt"], encoding="utf-8").read()
    with pytest.raises(render_arte.ArteInvalida):
        _entrega(pid, ARTE_RUIM, raiz, con, config)


def test_reprovado_pelas_regras_nao_chama_llm_e_abre_nova_rodada(con, raiz, config):
    pid = _peca(con, raiz)
    pipeline.proximo_passo(pid, raiz=raiz, con=con, config=config)
    _entrega(pid, COPY_CURA, raiz, con, config)
    r = _entrega(pid, ARTE_OK, raiz, con, config)
    # regras reprovam → sem delegação de compliance; volta ao redator com o parecer no prompt
    assert r["especialista"] == "redator"
    assert "cura garantida" in open(r["prompt"], encoding="utf-8").read()
    assert con.execute("SELECT voltas_compliance FROM pecas WHERE id=?", (pid,)).fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM custos WHERE especialista='compliance'").fetchone()[0] == 0
    assert json.loads((raiz / "conteudo" / pid / "etapas.json").read_text())["rodada"] == 2


def test_pauta_por_delegacao_cria_pecas(con, raiz, config):
    from test_pipeline import PAUTA
    import especialista
    prep = especialista.preparar("estrategista", raiz=raiz, contexto_extra="Semana alvo: 2026-09-28", config=config, pasta_prompt=raiz / "conteudo")
    assert prep["prompt"].name == "prompt_estrategista.md"
    saida = raiz / "conteudo" / "pauta_2026-09-28.yaml"
    especialista.entregar("estrategista", f"```\n{PAUTA}\n```", raiz=raiz, con=con, saida=saida, config=config, prompt_chars=1000)
    assert pipeline.criar_pecas_da_pauta(saida, raiz=raiz, con=con) == ["2026-09-29_ansiedade"]
