#!/usr/bin/env python3
"""Bot dedicado de aprovação (D2). Roda NO HOST (não no container do DUDS), como serviço systemd.

- A cada 30 s: peças em AGUARDANDO_HUMANO ou ESCALAR sem mensagem pendente → envia ao grupo
  (prévia da arte se existir + gancho/corpo + resumo do compliance + botões).
- Botões: AGUARDANDO_HUMANO → Aprovar / Ajustar / Descartar; ESCALAR → Liberar p/ aprovação / Ajustar / Descartar.
- Só IDs em config/agencia.yaml -> aprovadores decidem; qualquer outro recebe recusa e o clique é logado.
- Ajustar: o bot pede o texto; a próxima mensagem do mesmo aprovador vira ajuste.md e a peça volta a RASCUNHO.
- Comandos: /pendentes, /status <id>, /id (mostra o telegram_id de quem chamou).

.env: AGENCIA_TELEGRAM_BOT_TOKEN, AGENCIA_TELEGRAM_CHAT_ID (senão config -> telegram.grupo_marketing_chat_id).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import aprovacao  # noqa: E402
import db  # noqa: E402
import transicao  # noqa: E402
from comum import RAIZ, aprovadores_ids, caminho_db, carregar_config, carregar_env, logger  # noqa: E402

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: E402
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,  # noqa: E402
                          MessageHandler, filters)

LOG = logger("bot_aprovacao")
BOTOES = {
    "AGUARDANDO_HUMANO": [("✅ Aprovar", "APROVAR"), ("✏️ Ajustar", "AJUSTAR"), ("🗑 Descartar", "DESCARTAR")],
    "ESCALAR": [("⚠️ Liberar p/ aprovação", "LIBERAR"), ("✏️ Ajustar", "AJUSTAR"), ("🗑 Descartar", "DESCARTAR")],
}


def _teclado(estado: str, peca_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(rotulo, callback_data=f"{acao}|{peca_id}") for rotulo, acao in BOTOES[estado]]])


def _resumo_compliance(pasta: Path) -> str:
    p = pasta / "compliance.json"
    if not p.exists():
        return "compliance: sem parecer (ERRO — peça não deveria estar aqui)"
    c = json.loads(p.read_text(encoding="utf-8"))
    linhas = [f"Compliance: {c['resultado']}"]
    for i in c.get("itens", []):
        if i.get("status") == "falha" or (i.get("status") == "n/a" and "ausente" in i.get("fonte", "")):
            linhas.append(f"• item {i['n']} {i['status']}: {i['justificativa'][:140]}")
    if c.get("motivo_escalar"):
        linhas.append(f"Motivo do ESCALAR: {c['motivo_escalar'][:300]}")
    return "\n".join(linhas)


def _previa_copy(pasta: Path, limite: int = 900) -> str:
    p = pasta / "copy.md"
    if not p.exists():
        return "(sem copy.md)"
    txt = p.read_text(encoding="utf-8")
    ini = txt.find("## Gancho")
    corpo = txt[ini:] if ini >= 0 else txt
    return corpo[:limite] + ("…" if len(corpo) > limite else "")


def _texto_peca(raiz: Path, peca: dict) -> str:
    pasta = raiz / peca["pasta"]
    return (f"📌 {peca['id']} — {peca['formato']} · pilar {peca['pilar']} · {peca['canal']}\n"
            f"Estado: {peca['estado']}\n\n{_previa_copy(pasta)}\n\n{_resumo_compliance(pasta)}")


async def enviar_pendentes(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    raiz, con, chat_id = ctx.bot_data["raiz"], ctx.bot_data["con"], ctx.bot_data["chat_id"]
    for peca in aprovacao.pendentes_sem_mensagem(con):
        pasta = raiz / peca["pasta"]
        artes = sorted(pasta.glob("arte*.png"))
        texto = _texto_peca(raiz, peca)
        try:
            if artes:
                with open(artes[0], "rb") as f:
                    msg = await ctx.bot.send_photo(chat_id, f, caption=texto[:1024], reply_markup=_teclado(peca["estado"], peca["id"]))
                if len(texto) > 1024:
                    await ctx.bot.send_message(chat_id, texto[1024:4000])
            else:
                msg = await ctx.bot.send_message(chat_id, texto[:4000], reply_markup=_teclado(peca["estado"], peca["id"]))
            con.execute("INSERT INTO mensagens_aprovacao (peca_id, chat_id, message_id) VALUES (?,?,?)", (peca["id"], chat_id, msg.message_id))
            con.commit()
            LOG.info("enviada %s (%s) msg=%s", peca["id"], peca["estado"], msg.message_id)
        except Exception as exc:  # noqa: BLE001 — logar e seguir; próxima rodada tenta de novo
            LOG.error("falha ao enviar %s: %s", peca["id"], exc)


async def clique(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    raiz, con, config = ctx.bot_data["raiz"], ctx.bot_data["con"], ctx.bot_data["config"]
    acao, peca_id = q.data.split("|", 1)
    uid, nome = q.from_user.id, q.from_user.full_name
    if uid not in aprovadores_ids(config):
        LOG.warning("clique recusado: %s (%s) tentou %s em %s", uid, nome, acao, peca_id)
        await q.answer("Você não está na lista de aprovadores.", show_alert=True)
        return
    if acao == "AJUSTAR":
        ctx.user_data["ajuste_pendente"] = peca_id
        await q.message.reply_text(f"{nome}, responda aqui com o ajuste para {peca_id} (texto livre).")
        return
    try:
        estado = aprovacao.registrar_decisao(con, raiz, peca_id, acao, uid, nome, config=config)
    except (aprovacao.AprovadorInvalido, transicao.TransicaoInvalida, ValueError) as exc:
        LOG.error("decisão inválida %s %s por %s: %s", acao, peca_id, uid, exc)
        await q.message.reply_text(f"Não registrei: {exc}")
        return
    await q.edit_message_reply_markup(None)
    await q.message.reply_text(f"{acao} registrado por {nome} → {peca_id} agora em {estado}.")
    LOG.info("%s %s por %s -> %s", acao, peca_id, uid, estado)


async def texto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    peca_id = ctx.user_data.get("ajuste_pendente")
    if not peca_id or not update.message or not update.message.text:
        return
    raiz, con, config = ctx.bot_data["raiz"], ctx.bot_data["con"], ctx.bot_data["config"]
    uid, nome = update.effective_user.id, update.effective_user.full_name
    try:
        estado = aprovacao.registrar_decisao(con, raiz, peca_id, "AJUSTAR", uid, nome, update.message.text, config=config)
    except (aprovacao.AprovadorInvalido, transicao.TransicaoInvalida, ValueError) as exc:
        await update.message.reply_text(f"Não registrei o ajuste: {exc}")
        return
    ctx.user_data.pop("ajuste_pendente", None)
    await update.message.reply_text(f"Ajuste registrado por {nome}; {peca_id} voltou para {estado}. O DUDS refaz e reenvia.")


async def cmd_pendentes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    con = ctx.bot_data["con"]
    rows = con.execute("SELECT id, estado, atualizado_em FROM pecas WHERE estado IN ('AGUARDANDO_HUMANO','ESCALAR') ORDER BY atualizado_em").fetchall()
    await update.message.reply_text("\n".join(f"{r['id']} — {r['estado']} ({r['atualizado_em']})" for r in rows) or "Nada pendente.")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    con = ctx.bot_data["con"]
    if not ctx.args:
        await update.message.reply_text("uso: /status <id-da-peça>")
        return
    r = con.execute("SELECT id, estado, voltas_compliance, atualizado_em FROM pecas WHERE id=?", (ctx.args[0],)).fetchone()
    await update.message.reply_text(str(dict(r)) if r else "peça não encontrada")


async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"seu telegram_id: {update.effective_user.id}; chat_id: {update.effective_chat.id}")


def main() -> int:
    raiz = RAIZ
    config = carregar_config(raiz)
    env = carregar_env(raiz)
    token = env.get("AGENCIA_TELEGRAM_BOT_TOKEN")
    if not token:
        print("AGENCIA_TELEGRAM_BOT_TOKEN ausente no .env", file=sys.stderr)
        return 1
    chat_id = int(env.get("AGENCIA_TELEGRAM_CHAT_ID") or config.get("telegram", {}).get("grupo_marketing_chat_id") or 0)
    if not chat_id:
        print("chat_id de aprovação ausente (.env AGENCIA_TELEGRAM_CHAT_ID ou config telegram.grupo_marketing_chat_id)", file=sys.stderr)
        return 1
    if not aprovadores_ids(config):
        print("config -> aprovadores vazio; nada pode ser aprovado", file=sys.stderr)
        return 1
    app = Application.builder().token(token).build()
    app.bot_data.update({"raiz": raiz, "con": db.inicializar(caminho_db(config, raiz)), "config": config, "chat_id": chat_id})
    app.add_handler(CallbackQueryHandler(clique))
    app.add_handler(CommandHandler("pendentes", cmd_pendentes))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, texto))
    app.job_queue.run_repeating(enviar_pendentes, interval=30, first=5)
    LOG.info("bot de aprovação iniciado; chat_id=%s aprovadores=%s", chat_id, sorted(aprovadores_ids(config)))
    app.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0


if __name__ == "__main__":
    sys.exit(main())
