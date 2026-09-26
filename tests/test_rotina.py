import json

import custo
import notificar
import rotina
import transicao


def test_custo_resumo_e_teto(con, raiz, config):
    con.execute("INSERT INTO custos (especialista, modelo, tokens_entrada, tokens_saida, estimado) VALUES ('redator','m',1000,500,1)")
    con.execute("INSERT INTO custos (especialista, modelo, tokens_entrada, tokens_saida, estimado) VALUES ('compliance','m',200,100,0)")
    con.commit()
    import datetime as dt
    r = custo.resumo(con, config, dt.date.today().strftime("%Y-%m"))
    assert r["total_tokens"] == 1800 and r["por_especialista"]["redator"]["estimadas"] == 1 and r["estourados"] == []
    config["custo"]["teto_tokens_mes_por_especialista"] = 1000
    r = custo.resumo(con, config, dt.date.today().strftime("%Y-%m"))
    assert r["estourados"] == ["redator 1500 > 1000"]
    assert "| redator | 1500 |" in custo.tabela(r) and "Teto estourado" in custo.tabela(r)


def test_backup_consistente_e_rotativo(con, raiz):
    transicao.criar_peca(con, raiz, id="2026-10-03_b", canal="instagram", formato="post", pilar="3", objetivo="a", cta="c", autor="e")
    p = rotina.backup(raiz, con, manter=2)
    import db
    c2 = db.conectar(p)
    assert c2.execute("SELECT count(*) FROM pecas").fetchone()[0] == 1
    for i in range(3):
        (raiz / "dados" / "backups" / f"agencia-2020-01-0{i+1}.db").write_bytes(b"x")
    rotina.backup(raiz, con, manter=2)
    assert len(list((raiz / "dados" / "backups").glob("agencia-*.db"))) == 2


def test_resumo_diario_lista_estados_e_pendencias(con, raiz, config):
    transicao.criar_peca(con, raiz, id="2026-10-03_r", canal="instagram", formato="post", pilar="3", objetivo="a", cta="c", autor="e")
    for para, autor in [("RASCUNHO", "duds"), ("ARTE", "designer"), ("COMPLIANCE", "duds"), ("ESCALAR", "compliance")]:
        transicao.mover(con, raiz, "2026-10-03_r", para, autor, config=config)
    texto = rotina.resumo_diario(raiz, con, config)
    assert "ESCALAR 1" in texto and "Aguardando decisão humana: 2026-10-03_r" in texto and "Dinheiro: nenhum gasto novo" in texto
    assert (raiz / "relatorios").glob("resumo_diario_*.md")


def test_notificar_sem_token_nao_envia_e_com_token_posta(raiz):
    (raiz / ".env").write_text("", encoding="utf-8")
    assert notificar.enviar("x", raiz) is False
    (raiz / ".env").write_text("AGENCIA_TELEGRAM_BOT_TOKEN=t\nAGENCIA_TELEGRAM_CHAT_ID=-5\n", encoding="utf-8")
    chamadas = []
    class R: status_code = 200
    def fake(url, json=None, timeout=0):
        chamadas.append((url, json)); return R()
    assert notificar.enviar("olá", raiz, http=fake) is True
    assert "sendMessage" in chamadas[0][0] and chamadas[0][1] == {"chat_id": -5, "text": "olá"}
    assert "bot" in chamadas[0][0] and "t/" in chamadas[0][0]


def test_rotina_cli_backup_e_resumo(raiz, capsys):
    assert rotina.main(["backup", "--raiz", str(raiz), "--sem-notificar"]) == 0
    assert rotina.main(["resumo", "--raiz", str(raiz), "--sem-notificar"]) == 0
    assert list((raiz / "dados" / "backups").glob("agencia-*.db"))
