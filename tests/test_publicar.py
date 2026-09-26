import pytest

import aprovacao
import publicar_ig
import transicao
from conftest import ASSINATURA, COPY_OK


class FakeGraph:
    """Simula a Graph API: containers ficam FINISHED, publish devolve id fixo, insights fixos."""

    def __init__(self, falhar_em=None):
        self.chamadas, self.falhar_em, self.n = [], falhar_em, 0

    def post(self, caminho, **p):
        self.chamadas.append(("POST", caminho, p))
        if self.falhar_em and self.falhar_em in caminho:
            raise publicar_ig.ErroPublicacao("simulada")
        self.n += 1
        return {"id": f"c{self.n}" if caminho.endswith("/media") else "midia123"}

    def get(self, caminho, **p):
        self.chamadas.append(("GET", caminho, p))
        if caminho.endswith("/insights") and "midia" in caminho:
            return {"data": [{"name": "reach", "values": [{"value": 1234}]}, {"name": "saved", "values": [{"value": 56}]},
                             {"name": "shares", "values": [{"value": 7}]}, {"name": "comments", "values": [{"value": 3}]}, {"name": "likes", "values": [{"value": 89}]}]}
        if p.get("fields") == "status_code":
            return {"status_code": "FINISHED"}
        if p.get("fields") == "permalink":
            return {"permalink": "https://www.instagram.com/p/abc/"}
        if "followers_count" in p.get("fields", ""):
            return {"followers_count": 1500, "media_count": 42, "username": "teste"}
        return {"data": [{"name": "reach", "total_value": {"value": 900}}]}


def _aprovada(con, raiz, config, pid="2026-10-02_pub", formato="post", n_artes=1):
    transicao.criar_peca(con, raiz, id=pid, canal="instagram", formato=formato, pilar="3", objetivo="alcance", cta="Salve.", autor="estrategista")
    pasta = raiz / "conteudo" / pid
    (pasta / "copy.md").write_text(COPY_OK, encoding="utf-8")
    for i in range(1, n_artes + 1):
        (pasta / f"arte_{i:02d}.png").write_bytes(b"\x89PNG fake")
    for para, autor in [("RASCUNHO", "duds"), ("ARTE", "designer"), ("COMPLIANCE", "duds"), ("APROVADO_COMPLIANCE", "compliance"), ("AGUARDANDO_HUMANO", "duds")]:
        transicao.mover(con, raiz, pid, para, autor, config=config)
    aprovacao.registrar_decisao(con, raiz, pid, "APROVAR", 111, "Fabbro", config=config)
    (raiz / ".env").write_text(f"AGENCIA_IG_USER_ID=17841400\nAGENCIA_MIDIA_DIR={raiz / 'midia'}\nAGENCIA_MIDIA_BASE_URL=https://exemplo.test/agencia-midia\n", encoding="utf-8")
    return pid


def test_legenda_montada_do_copy():
    leg = publicar_ig.montar_legenda(COPY_OK)
    assert leg.startswith("Ansiedade não é frescura.") and ASSINATURA in leg and leg.endswith("#saudemental #ansiedade")
    assert "## " not in leg and "Notas para o designer" not in leg
    with pytest.raises(publicar_ig.ErroPublicacao, match="Assinatura"):
        publicar_ig.montar_legenda(COPY_OK.replace(ASSINATURA, "x"))
    with pytest.raises(publicar_ig.ErroPublicacao, match="2200"):
        publicar_ig.montar_legenda(COPY_OK.replace("Cada caso é individual.", "x" * 2300))


def test_agendar_exige_aprovacao_registrada(con, raiz, config):
    transicao.criar_peca(con, raiz, id="2026-10-02_na", canal="instagram", formato="post", pilar="3", objetivo="a", cta="c", autor="e")
    for para, autor in [("RASCUNHO", "duds"), ("ARTE", "designer"), ("COMPLIANCE", "duds"), ("APROVADO_COMPLIANCE", "compliance"), ("AGUARDANDO_HUMANO", "duds"), ("APROVADO", "telegram:111")]:
        transicao.mover(con, raiz, "2026-10-02_na", para, autor, config=config)   # APROVADO sem linha em aprovacoes
    with pytest.raises(transicao.TransicaoInvalida, match="aprovacoes"):
        publicar_ig.agendar(con, raiz, "2026-10-02_na", "2026-10-02 18:30", config)


def test_agendar_converte_fuso_e_tick_publica_e_mede(con, raiz, config):
    pid = _aprovada(con, raiz, config, formato="carrossel", n_artes=3)
    r = publicar_ig.agendar(con, raiz, pid, "2026-10-02 18:30", config)
    assert r["quando_utc"] == "2026-10-02T21:30:00Z"                      # America/Sao_Paulo = UTC-3
    fake = FakeGraph()
    assert publicar_ig.tick(con, raiz, config, cli=fake, agora="2026-10-02T21:00:00Z") == []   # ainda não venceu
    res = publicar_ig.tick(con, raiz, config, cli=fake, agora="2026-10-02T21:31:00Z")
    assert res[0]["ok"] and res[0]["midia_id"] == "midia123"
    assert con.execute("SELECT estado FROM pecas WHERE id=?", (pid,)).fetchone()[0] == "PUBLICADO"
    posts = [c for c in fake.chamadas if c[0] == "POST"]
    assert len([c for c in posts if c[2].get("is_carousel_item")]) == 3 and posts[-2][2]["media_type"] == "CAROUSEL"
    assert posts[-2][2]["caption"].startswith("Ansiedade") and posts[-1][1].endswith("media_publish")
    assert all(u.startswith("https://exemplo.test/agencia-midia/") for c in posts[:3] for u in [c[2]["image_url"]])
    assert len(list((raiz / "midia").glob("*.png"))) == 3
    # medir: antes de 20 h não mede; depois grava métricas e vai a MEDIDO
    assert publicar_ig.medir(con, raiz, config, cli=fake, agora="2026-10-03T05:00:00Z") == []
    m = publicar_ig.medir(con, raiz, config, cli=fake, agora="2026-10-03T21:00:00Z")
    assert m[0]["ok"] and m[0]["metricas"]["alcance"] == 1234.0
    assert con.execute("SELECT estado FROM pecas WHERE id=?", (pid,)).fetchone()[0] == "MEDIDO"
    row = con.execute("SELECT valor, data FROM metricas WHERE fonte='instagram' AND metrica='salvamentos' AND peca_id=?", (pid,)).fetchone()
    assert (row["valor"], row["data"]) == (56.0, "2026-10-02")


def test_story_usa_media_type_stories(con, raiz, config):
    pid = _aprovada(con, raiz, config, pid="2026-10-02_st", formato="story")
    publicar_ig.agendar(con, raiz, pid, "2026-10-02 10:00", config)
    fake = FakeGraph()
    publicar_ig.tick(con, raiz, config, cli=fake, agora="2026-10-02T13:01:00Z")
    assert any(c[2].get("media_type") == "STORIES" for c in fake.chamadas if c[0] == "POST")


def test_falha_mantem_agendado_ate_3_tentativas(con, raiz, config):
    pid = _aprovada(con, raiz, config)
    publicar_ig.agendar(con, raiz, pid, "2026-10-02 10:00", config)
    fake = FakeGraph(falhar_em="media_publish")
    for i in range(1, 4):
        r = publicar_ig.tick(con, raiz, config, cli=fake, agora="2026-10-02T13:01:00Z")
        assert not r[0]["ok"] and r[0]["tentativa"] == i
    a = con.execute("SELECT status, erro FROM agendamentos WHERE peca_id=?", (pid,)).fetchone()
    assert a["status"] == "FALHOU" and "simulada" in a["erro"]
    assert con.execute("SELECT estado FROM pecas WHERE id=?", (pid,)).fetchone()[0] == "AGENDADO"
    assert publicar_ig.tick(con, raiz, config, cli=fake, agora="2026-10-02T13:05:00Z") == []      # não insiste


def test_cancelar_exige_aprovador(con, raiz, config):
    pid = _aprovada(con, raiz, config)
    publicar_ig.agendar(con, raiz, pid, "2026-10-02 10:00", config)
    with pytest.raises(transicao.TransicaoInvalida):
        publicar_ig.cancelar(con, raiz, pid, "duds", config)
    assert publicar_ig.cancelar(con, raiz, pid, "telegram:111", config) == "DESCARTADO"
    assert con.execute("SELECT status FROM agendamentos WHERE peca_id=?", (pid,)).fetchone()[0] == "CANCELADO"


def test_medir_conta(con, raiz, config):
    (raiz / ".env").write_text("AGENCIA_IG_USER_ID=17841400\n", encoding="utf-8")
    r = publicar_ig.medir_conta(con, raiz, cli=FakeGraph(), dia="2026-10-02")
    assert r["seguidores"] == 1500.0 and r["alcance_conta"] == 900.0
    assert con.execute("SELECT count(*) FROM metricas WHERE entidade_id='conta:17841400'").fetchone()[0] == 3
