import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import db  # noqa: E402


@pytest.fixture
def con(tmp_path):
    c = db.inicializar(tmp_path / "t.db")
    yield c
    c.close()


def _peca(con, pid="2026-09-29_teste", estado="PAUTA"):
    con.execute(
        "INSERT INTO pecas (id, canal, formato, pilar, objetivo, cta, estado, pasta) VALUES (?,?,?,?,?,?,?,?)",
        (pid, "instagram", "post", "educacao", "alcance", "salvar", estado, f"conteudo/{pid}"),
    )


def test_cria_todas_as_tabelas(con):
    nomes = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(db.TABELAS) <= nomes


def test_init_e_idempotente(tmp_path):
    p = tmp_path / "t.db"
    db.inicializar(p).close()
    c = db.inicializar(p)
    _peca(c)
    c.commit()
    c.close()
    c = db.inicializar(p)  # terceira vez, com dados: não pode apagar nada
    assert c.execute("SELECT count(*) FROM pecas").fetchone()[0] == 1


def test_estado_invalido_e_rejeitado(con):
    with pytest.raises(sqlite3.IntegrityError):
        _peca(con, estado="PUBLICADO_SEM_QUERER")


def test_todos_os_estados_da_especificacao_sao_aceitos(con):
    esperados = {"PAUTA", "RASCUNHO", "ARTE", "COMPLIANCE", "APROVADO_COMPLIANCE", "REPROVADO", "ESCALAR",
                 "AGUARDANDO_HUMANO", "APROVADO", "AJUSTAR", "DESCARTADO", "AGENDADO", "PUBLICADO", "MEDIDO"}
    assert esperados == set(db.ESTADOS)
    for i, e in enumerate(db.ESTADOS):
        _peca(con, pid=f"2026-01-01_e{i}", estado=e)


def test_transicao_exige_peca_existente(con):
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO transicoes (peca_id, de, para, autor) VALUES ('nao-existe','PAUTA','RASCUNHO','duds')")


def test_transicao_registra_autor_e_timestamp(con):
    _peca(con)
    con.execute("INSERT INTO transicoes (peca_id, de, para, autor, motivo) VALUES (?,?,?,?,?)",
                ("2026-09-29_teste", None, "PAUTA", "estrategista", "criação"))
    r = con.execute("SELECT autor, timestamp FROM transicoes").fetchone()
    assert r["autor"] == "estrategista" and r["timestamp"].endswith("Z")


def test_aprovacao_so_aceita_decisoes_validas(con):
    _peca(con)
    con.execute("INSERT INTO aprovacoes (peca_id, decisao, telegram_id) VALUES (?,?,?)", ("2026-09-29_teste", "APROVAR", 123))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO aprovacoes (peca_id, decisao, telegram_id) VALUES (?,?,?)", ("2026-09-29_teste", "OK", 123))


def test_metrica_nao_duplica_mesmo_dado(con):
    con.execute("INSERT INTO metricas (fonte, entidade_id, data, metrica, valor) VALUES ('google_ads','c1','2026-09-25','cliques',10)")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO metricas (fonte, entidade_id, data, metrica, valor) VALUES ('google_ads','c1','2026-09-25','cliques',11)")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO metricas (fonte, entidade_id, data, metrica, valor) VALUES ('estimativa','c1','2026-09-25','cliques',11)")


def test_custo_por_especialista(con):
    con.execute("INSERT INTO custos (especialista, modelo, tokens_entrada, tokens_saida) VALUES ('compliance','gpt-x',100,50)")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO custos (especialista, modelo, tokens_entrada, tokens_saida) VALUES ('estagiario','gpt-x',1,1)")
    assert con.execute("SELECT custo_estimado FROM custos").fetchone()[0] is None
