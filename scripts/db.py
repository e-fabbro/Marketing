#!/usr/bin/env python3
"""Schema do dados/agencia.db e inicialização idempotente.

Uso:  python3 scripts/db.py --init [--db caminho]
Tabelas: pecas, transicoes, aprovacoes, metricas, custos.
A máquina de estados (transições permitidas) fica em scripts/transicao.py (Fase 2);
aqui só a lista de estados válidos, usada como CHECK.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DB_PADRAO = RAIZ / "dados" / "agencia.db"

ESTADOS = (
    "PAUTA", "RASCUNHO", "ARTE", "COMPLIANCE", "APROVADO_COMPLIANCE", "REPROVADO", "ESCALAR",
    "AGUARDANDO_HUMANO", "APROVADO", "AJUSTAR", "DESCARTADO", "AGENDADO", "PUBLICADO", "MEDIDO",
)
DECISOES = ("APROVAR", "AJUSTAR", "DESCARTAR", "LIBERAR")   # LIBERAR: humano tira de ESCALAR e manda para aprovação
FONTES_METRICA = ("google_ads", "instagram", "gbp", "ga4")
ESPECIALISTAS = ("estrategista", "redator", "designer", "compliance", "trafego", "analista")


def _lista_sql(valores) -> str:
    return ", ".join(f"'{v}'" for v in valores)


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS pecas (
    id            TEXT PRIMARY KEY,                 -- AAAA-MM-DD_slug
    canal         TEXT NOT NULL,                    -- instagram | google_business | google_ads | ...
    formato       TEXT NOT NULL,                    -- post | carrossel | reels | story | anuncio | artigo
    pilar         TEXT NOT NULL,
    objetivo      TEXT NOT NULL,
    cta           TEXT NOT NULL,
    estado        TEXT NOT NULL CHECK (estado IN ({_lista_sql(ESTADOS)})),
    voltas_compliance INTEGER NOT NULL DEFAULT 0,
    pasta         TEXT NOT NULL,                    -- conteudo/AAAA-MM-DD_slug
    criado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    atualizado_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS transicoes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    peca_id   TEXT NOT NULL REFERENCES pecas(id),
    de        TEXT CHECK (de IS NULL OR de IN ({_lista_sql(ESTADOS)})),   -- NULL = criação
    para      TEXT NOT NULL CHECK (para IN ({_lista_sql(ESTADOS)})),
    autor     TEXT NOT NULL,                        -- especialista, 'duds', 'publicador' ou 'telegram:<id>'
    motivo    TEXT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_transicoes_peca ON transicoes(peca_id, id);

CREATE TABLE IF NOT EXISTS aprovacoes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    peca_id       TEXT NOT NULL REFERENCES pecas(id),
    decisao       TEXT NOT NULL CHECK (decisao IN ({_lista_sql(DECISOES)})),
    telegram_id   INTEGER NOT NULL,                 -- validado contra config/agencia.yaml -> aprovadores
    telegram_nome TEXT,
    comentario    TEXT,
    timestamp     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS metricas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fonte       TEXT NOT NULL CHECK (fonte IN ({_lista_sql(FONTES_METRICA)})),
    entidade_id TEXT NOT NULL,                      -- id da campanha, do post, do perfil...
    peca_id     TEXT REFERENCES pecas(id),          -- NULL quando não é uma peça nossa
    data        TEXT NOT NULL,                      -- AAAA-MM-DD do dado
    metrica     TEXT NOT NULL,                      -- impressoes, cliques, custo, alcance, salvamentos...
    valor       REAL NOT NULL,
    coletado_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (fonte, entidade_id, data, metrica)
);

CREATE TABLE IF NOT EXISTS custos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    especialista   TEXT NOT NULL CHECK (especialista IN ({_lista_sql(ESPECIALISTAS)})),
    modelo         TEXT NOT NULL,
    tokens_entrada INTEGER NOT NULL,
    tokens_saida   INTEGER NOT NULL,
    custo_estimado REAL,                            -- NULL: provedor por assinatura (sem preço por token)
    estimado       INTEGER NOT NULL DEFAULT 0,      -- 1: tokens estimados (chars/4) por falta de usage na delegação
    peca_id        TEXT REFERENCES pecas(id),
    timestamp      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_custos_mes ON custos(especialista, timestamp);

CREATE TABLE IF NOT EXISTS agendamentos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    peca_id       TEXT NOT NULL REFERENCES pecas(id),
    canal         TEXT NOT NULL,                    -- instagram
    quando_utc    TEXT NOT NULL,                    -- ISO UTC
    status        TEXT NOT NULL DEFAULT 'AGENDADO' CHECK (status IN ('AGENDADO','PUBLICADO','FALHOU','CANCELADO')),
    tentativas    INTEGER NOT NULL DEFAULT 0,
    midia_id      TEXT,                             -- id da mídia no Instagram
    permalink     TEXT,
    publicado_em  TEXT,
    erro          TEXT,
    criado_em     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS ix_agend_status ON agendamentos(status, quando_utc);

CREATE TABLE IF NOT EXISTS mensagens_aprovacao (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    peca_id    TEXT NOT NULL REFERENCES pecas(id),
    chat_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    enviado_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    respondido_em TEXT
);
CREATE INDEX IF NOT EXISTS ix_msg_peca ON mensagens_aprovacao(peca_id);
"""

TABELAS = ("pecas", "transicoes", "aprovacoes", "metricas", "custos", "mensagens_aprovacao", "agendamentos")

# Colunas adicionadas depois da criação inicial: CREATE TABLE IF NOT EXISTS não migra tabelas antigas.
MIGRACOES = (
    ("custos", "estimado", "INTEGER NOT NULL DEFAULT 0"),
)


def _sql_criacao(tabela: str) -> str:
    """Extrai do SCHEMA o CREATE TABLE de uma tabela (para reconstruções)."""
    ini = SCHEMA.index(f"CREATE TABLE IF NOT EXISTS {tabela} (")
    fim = SCHEMA.index(");", ini) + 2
    return SCHEMA[ini:fim]


def migrar(con: sqlite3.Connection) -> list[str]:
    """Migrações idempotentes: colunas novas e CHECKs alterados (SQLite exige reconstruir a tabela)."""
    aplicadas = []
    for tabela, coluna, tipo in MIGRACOES:
        existentes = {r[1] for r in con.execute(f"PRAGMA table_info({tabela})")}
        if existentes and coluna not in existentes:
            con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
            aplicadas.append(f"{tabela}.{coluna}")
    # CHECK de aprovacoes.decisao sem LIBERAR (bancos criados antes de D8)
    row = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='aprovacoes'").fetchone()
    if row and "'LIBERAR'" not in row[0]:
        con.executescript(
            "ALTER TABLE aprovacoes RENAME TO aprovacoes_old;\n"
            + _sql_criacao("aprovacoes") + "\n"
            "INSERT INTO aprovacoes (id, peca_id, decisao, telegram_id, telegram_nome, comentario, timestamp) "
            "SELECT id, peca_id, decisao, telegram_id, telegram_nome, comentario, timestamp FROM aprovacoes_old;\n"
            "DROP TABLE aprovacoes_old;")
        aplicadas.append("aprovacoes.decisao CHECK (+LIBERAR)")
    con.commit()
    return aplicadas


def conectar(caminho: Path | str = DB_PADRAO) -> sqlite3.Connection:
    """Conexão com FK ligada e WAL. Todo script deve usar esta função."""
    con = sqlite3.connect(str(caminho))
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.row_factory = sqlite3.Row
    return con


def inicializar(caminho: Path | str = DB_PADRAO) -> sqlite3.Connection:
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    con = conectar(caminho)
    con.executescript(SCHEMA)
    con.commit()
    migrar(con)
    return con


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--init", action="store_true", help="cria as tabelas se não existirem")
    ap.add_argument("--db", default=str(DB_PADRAO))
    args = ap.parse_args()
    if not args.init:
        ap.error("use --init")
    con = inicializar(args.db)
    nomes = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print(f"ok: {args.db} tabelas={','.join(n for n in nomes if n in TABELAS)}")


if __name__ == "__main__":
    main()
