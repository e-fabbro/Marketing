import pytest

import aprovacao
import transicao


def _aguardando(con, raiz, config, pid="2026-09-29_x"):
    transicao.criar_peca(con, raiz, id=pid, canal="instagram", formato="post", pilar="3", objetivo="alcance", cta="salve", autor="estrategista")
    for para, autor in [("RASCUNHO", "duds"), ("ARTE", "duds"), ("COMPLIANCE", "duds"), ("APROVADO_COMPLIANCE", "compliance"), ("AGUARDANDO_HUMANO", "duds")]:
        transicao.mover(con, raiz, pid, para, autor, config=config)
    return pid


def test_aprovar_por_aprovador(con, raiz, config):
    pid = _aguardando(con, raiz, config)
    con.execute("INSERT INTO mensagens_aprovacao (peca_id, chat_id, message_id) VALUES (?,?,?)", (pid, -1, 5))
    assert aprovacao.registrar_decisao(con, raiz, pid, "APROVAR", 111, "Fabbro", config=config) == "APROVADO"
    r = con.execute("SELECT decisao, telegram_id FROM aprovacoes").fetchone()
    assert (r["decisao"], r["telegram_id"]) == ("APROVAR", 111)
    assert con.execute("SELECT respondido_em FROM mensagens_aprovacao").fetchone()[0] is not None
    assert aprovacao.pendentes_sem_mensagem(con) == []


def test_nao_aprovador_e_recusado_e_nada_muda(con, raiz, config):
    pid = _aguardando(con, raiz, config)
    with pytest.raises(aprovacao.AprovadorInvalido):
        aprovacao.registrar_decisao(con, raiz, pid, "APROVAR", 999, config=config)
    assert con.execute("SELECT estado FROM pecas").fetchone()[0] == "AGUARDANDO_HUMANO"
    assert con.execute("SELECT count(*) FROM aprovacoes").fetchone()[0] == 0


def test_ajustar_exige_comentario_e_volta_a_rascunho(con, raiz, config):
    pid = _aguardando(con, raiz, config)
    with pytest.raises(ValueError):
        aprovacao.registrar_decisao(con, raiz, pid, "AJUSTAR", 222, config=config)
    assert aprovacao.registrar_decisao(con, raiz, pid, "AJUSTAR", 222, "Jessica", "troque o gancho", config=config) == "RASCUNHO"
    assert "troque o gancho" in (raiz / "conteudo" / pid / "ajuste.md").read_text()


def test_descartar(con, raiz, config):
    pid = _aguardando(con, raiz, config)
    assert aprovacao.registrar_decisao(con, raiz, pid, "DESCARTAR", 111, config=config) == "DESCARTADO"


def test_pendentes_sem_mensagem(con, raiz, config):
    pid = _aguardando(con, raiz, config)
    assert [p["id"] for p in aprovacao.pendentes_sem_mensagem(con)] == [pid]
    con.execute("INSERT INTO mensagens_aprovacao (peca_id, chat_id, message_id) VALUES (?,?,?)", (pid, -1, 5))
    assert aprovacao.pendentes_sem_mensagem(con) == []


def _escalada(con, raiz, config, pid="2026-09-29_e"):
    transicao.criar_peca(con, raiz, id=pid, canal="instagram", formato="post", pilar="3", objetivo="alcance", cta="salve", autor="estrategista")
    for para, autor in [("RASCUNHO", "duds"), ("ARTE", "duds"), ("COMPLIANCE", "duds"), ("ESCALAR", "compliance")]:
        transicao.mover(con, raiz, pid, para, autor, config=config)
    return pid


def test_escalar_liberar_ajustar_descartar(con, raiz, config):
    pid = _escalada(con, raiz, config)
    assert pid in [p["id"] for p in aprovacao.pendentes_sem_mensagem(con)]
    with pytest.raises(transicao.TransicaoInvalida):        # APROVAR direto de ESCALAR não existe
        aprovacao.registrar_decisao(con, raiz, pid, "APROVAR", 111, config=config)
    assert aprovacao.registrar_decisao(con, raiz, pid, "LIBERAR", 111, config=config) == "AGUARDANDO_HUMANO"
    pid2 = _escalada(con, raiz, config, "2026-09-29_f")
    assert aprovacao.registrar_decisao(con, raiz, pid2, "AJUSTAR", 222, "J", "tire o preço", config=config) == "RASCUNHO"
    pid3 = _escalada(con, raiz, config, "2026-09-29_g")
    assert aprovacao.registrar_decisao(con, raiz, pid3, "DESCARTAR", 222, config=config) == "DESCARTADO"


def test_decisao_e_atomica(con, raiz, config, monkeypatch):
    pid = _aguardando(con, raiz, config)
    original = transicao.mover
    def falha(*a, **k):
        raise RuntimeError("simulado")
    monkeypatch.setattr(transicao, "mover", falha)
    with pytest.raises(RuntimeError):
        aprovacao.registrar_decisao(con, raiz, pid, "APROVAR", 111, config=config)
    monkeypatch.setattr(transicao, "mover", original)
    assert con.execute("SELECT count(*) FROM aprovacoes").fetchone()[0] == 0
    assert con.execute("SELECT estado FROM pecas WHERE id=?", (pid,)).fetchone()[0] == "AGUARDANDO_HUMANO"


def test_reenvia_quando_o_estado_muda_depois_da_mensagem(con, raiz, config):
    pid = _escalada(con, raiz, config)
    con.execute("INSERT INTO mensagens_aprovacao (peca_id, chat_id, message_id, enviado_em) VALUES (?,?,?,?)", (pid, -1, 5, "2000-01-01T00:00:00Z"))
    con.commit()
    # a mensagem é anterior à última mudança de estado → deve reenviar
    assert [p["id"] for p in aprovacao.pendentes_sem_mensagem(con)] == [pid]
    con.execute("UPDATE mensagens_aprovacao SET enviado_em='2999-01-01T00:00:00Z'")
    con.commit()
    assert aprovacao.pendentes_sem_mensagem(con) == []
