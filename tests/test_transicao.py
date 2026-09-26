import pytest

import transicao
from transicao import TransicaoInvalida


def _nova(con, raiz, pid="2026-09-29_teste"):
    return transicao.criar_peca(con, raiz, id=pid, canal="instagram", formato="post", pilar="3",
                                objetivo="alcance", cta="salve", autor="estrategista")


def test_criar_registra_pauta_e_yaml(con, raiz):
    p = _nova(con, raiz)
    assert p["estado"] == "PAUTA"
    assert (raiz / "conteudo" / "2026-09-29_teste" / "peca.yaml").exists()
    assert con.execute("SELECT para FROM transicoes").fetchone()[0] == "PAUTA"


def test_caminho_feliz_ate_publicado(con, raiz, config):
    _nova(con, raiz)
    seq = [("RASCUNHO", "duds"), ("ARTE", "duds"), ("COMPLIANCE", "duds"), ("APROVADO_COMPLIANCE", "compliance"),
           ("AGUARDANDO_HUMANO", "duds"), ("APROVADO", "telegram:111"), ("AGENDADO", "publicador"),
           ("PUBLICADO", "publicador"), ("MEDIDO", "analista")]
    for para, autor in seq:
        assert transicao.mover(con, raiz, "2026-09-29_teste", para, autor, config=config)["estado"] == para
    hist = con.execute("SELECT count(*) FROM transicoes WHERE peca_id='2026-09-29_teste'").fetchone()[0]
    assert hist == len(seq) + 1


def test_pular_compliance_e_erro(con, raiz, config):
    _nova(con, raiz)
    transicao.mover(con, raiz, "2026-09-29_teste", "RASCUNHO", "duds", config=config)
    with pytest.raises(TransicaoInvalida):
        transicao.mover(con, raiz, "2026-09-29_teste", "AGUARDANDO_HUMANO", "duds", config=config)
    with pytest.raises(TransicaoInvalida):
        transicao.mover(con, raiz, "2026-09-29_teste", "APROVADO", "telegram:111", config=config)
    assert con.execute("SELECT estado FROM pecas").fetchone()[0] == "RASCUNHO"


def test_aprovado_exige_id_de_aprovador(con, raiz, config):
    _nova(con, raiz)
    for para, autor in [("RASCUNHO", "duds"), ("ARTE", "duds"), ("COMPLIANCE", "duds"),
                        ("APROVADO_COMPLIANCE", "compliance"), ("AGUARDANDO_HUMANO", "duds")]:
        transicao.mover(con, raiz, "2026-09-29_teste", para, autor, config=config)
    for autor in ("duds", "telegram:999", "telegram:abc", "111"):
        with pytest.raises(TransicaoInvalida):
            transicao.mover(con, raiz, "2026-09-29_teste", "APROVADO", autor, config=config)
    assert transicao.mover(con, raiz, "2026-09-29_teste", "APROVADO", "telegram:222", config=config)["estado"] == "APROVADO"


def test_terceira_reprovacao_exige_escalar(con, raiz, config):
    _nova(con, raiz)
    pid = "2026-09-29_teste"
    transicao.mover(con, raiz, pid, "RASCUNHO", "duds", config=config)
    for volta in (1, 2):
        transicao.mover(con, raiz, pid, "ARTE", "duds", config=config)
        transicao.mover(con, raiz, pid, "COMPLIANCE", "duds", config=config)
        p = transicao.mover(con, raiz, pid, "REPROVADO", "compliance", config=config)
        assert p["voltas_compliance"] == volta
        transicao.mover(con, raiz, pid, "RASCUNHO", "duds", config=config)
    transicao.mover(con, raiz, pid, "ARTE", "duds", config=config)
    transicao.mover(con, raiz, pid, "COMPLIANCE", "duds", config=config)
    transicao.mover(con, raiz, pid, "REPROVADO", "compliance", config=config)
    with pytest.raises(TransicaoInvalida, match="ESCALAR"):
        transicao.mover(con, raiz, pid, "RASCUNHO", "duds", config=config)
    assert transicao.mover(con, raiz, pid, "ESCALAR", "duds", config=config)["estado"] == "ESCALAR"
    with pytest.raises(TransicaoInvalida):          # sair de ESCALAR é decisão humana
        transicao.mover(con, raiz, pid, "RASCUNHO", "duds", config=config)


def test_cli_transicao_invalida_retorna_2(con, raiz, capsys):
    con.close()
    assert transicao.main(["--raiz", str(raiz), "criar", "--id", "2026-09-29_cli", "--canal", "instagram", "--formato", "post",
                           "--pilar", "3", "--objetivo", "alcance", "--cta", "salve", "--autor", "estrategista"]) == 0
    assert transicao.main(["--raiz", str(raiz), "mover", "--peca", "2026-09-29_cli", "--para", "PUBLICADO", "--autor", "duds"]) == 2
    assert "ERRO transição" in capsys.readouterr().err
