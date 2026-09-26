"""Lógica pura de aprovação humana (sem Telegram), usada pelo bot e pelos testes.

registrar_decisao(con, raiz, peca_id, decisao, telegram_id, nome, comentario, config)
  - valida telegram_id contra config -> aprovadores (senão AprovadorInvalido)
  - grava em `aprovacoes`
  - de AGUARDANDO_HUMANO: APROVAR -> APROVADO; DESCARTAR -> DESCARTADO; AJUSTAR -> AJUSTAR -> RASCUNHO
  - de ESCALAR (dúvida normativa): LIBERAR -> AGUARDANDO_HUMANO; AJUSTAR -> RASCUNHO; DESCARTAR -> DESCARTADO
  Comentário de AJUSTAR vai para conteudo/<peça>/ajuste.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transicao  # noqa: E402
from comum import agora_iso, aprovadores_ids, carregar_config  # noqa: E402

MAPA = {
    "AGUARDANDO_HUMANO": {"APROVAR": "APROVADO", "AJUSTAR": "AJUSTAR", "DESCARTAR": "DESCARTADO"},
    "ESCALAR": {"LIBERAR": "AGUARDANDO_HUMANO", "AJUSTAR": "RASCUNHO", "DESCARTAR": "DESCARTADO"},
}


class AprovadorInvalido(Exception):
    pass


def registrar_decisao(con, raiz: Path, peca_id: str, decisao: str, telegram_id: int, nome: str = "",
                      comentario: str = "", config: dict | None = None) -> str:
    config = config or carregar_config(raiz)
    if int(telegram_id) not in aprovadores_ids(config):
        raise AprovadorInvalido(f"telegram_id {telegram_id} não está em aprovadores")
    row = con.execute("SELECT estado, pasta FROM pecas WHERE id=?", (peca_id,)).fetchone()
    if not row:
        raise transicao.TransicaoInvalida(f"peça {peca_id} não existe")
    opcoes = MAPA.get(row["estado"], {})
    if decisao not in opcoes:
        raise transicao.TransicaoInvalida(f"{peca_id} em {row['estado']}: decisão {decisao} não se aplica")
    if decisao == "AJUSTAR" and not comentario.strip():
        raise ValueError("AJUSTAR exige comentário")
    autor = f"telegram:{int(telegram_id)}"
    if decisao == "AJUSTAR":
        (raiz / row["pasta"]).mkdir(parents=True, exist_ok=True)
        (raiz / row["pasta"] / "ajuste.md").write_text(f"# Ajuste pedido por {nome or autor} em {agora_iso()}\n\n{comentario}\n", encoding="utf-8")
    peca = transicao.mover(con, raiz, peca_id, opcoes[decisao], autor, comentario or decisao.lower(), config)
    con.execute("INSERT INTO aprovacoes (peca_id, decisao, telegram_id, telegram_nome, comentario) VALUES (?,?,?,?,?)",
                (peca_id, decisao, int(telegram_id), nome, comentario))
    con.execute("UPDATE mensagens_aprovacao SET respondido_em=? WHERE peca_id=? AND respondido_em IS NULL", (agora_iso(), peca_id))
    con.commit()
    if peca["estado"] == "AJUSTAR":
        peca = transicao.mover(con, raiz, peca_id, "RASCUNHO", "bot_aprovacao", "ajuste humano registrado", config)
    return peca["estado"]


def pendentes_sem_mensagem(con) -> list[dict]:
    rows = con.execute("""SELECT p.* FROM pecas p WHERE p.estado IN ('AGUARDANDO_HUMANO','ESCALAR')
                          AND NOT EXISTS (SELECT 1 FROM mensagens_aprovacao m WHERE m.peca_id=p.id AND m.respondido_em IS NULL)
                          ORDER BY p.atualizado_em""").fetchall()
    return [dict(r) for r in rows]
