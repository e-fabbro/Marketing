import json
import threading
from urllib import request

import pytest
import yaml

import render_arte
import render_servico

try:
    CHROMIUM = render_arte.encontrar_chromium()
except RuntimeError:
    CHROMIUM = None
precisa_chromium = pytest.mark.skipif(CHROMIUM is None, reason="Chromium não encontrado")

ASS = "Dra. Jessica Jacomelli — CRM-DF 27043 — RQE 22349"


def _arte(template, formatos, n):
    return {"peca": "2026-09-30_x", "template": template, "formatos": formatos,
            "slides": [{"titulo": f"Título {i}", "corpo": "Corpo curto com um trecho em destaque para teste.", "destaque": "destaque", "rodape": f"{i}/{n}"} for i in range(1, n + 1)],
            "assinatura": ASS, "alt_text": "Arte de teste."}


def _grava(raiz, arte, pid="2026-09-30_x"):
    pasta = raiz / "conteudo" / pid
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "arte.yaml").write_text(yaml.safe_dump(arte, allow_unicode=True), encoding="utf-8")
    return pasta


def test_validacao_rejeita_incompatibilidades():
    with pytest.raises(render_arte.ArteInvalida, match="incompat"):
        render_arte.validar(_arte("story", ["1080x1080"], 1))
    with pytest.raises(render_arte.ArteInvalida, match="slides"):
        render_arte.validar(_arte("post", ["1080x1080"], 2))
    with pytest.raises(render_arte.ArteInvalida, match="slides"):
        render_arte.validar(_arte("carrossel", ["1080x1350"], 1))
    a = _arte("post", ["1080x1080"], 1); a["slides"][0]["corpo"] = "x" * 221
    with pytest.raises(render_arte.ArteInvalida, match="corpo"):
        render_arte.validar(a)
    a = _arte("post", ["1080x1080"], 1); a["assinatura"] = "Dra. TODO"
    with pytest.raises(render_arte.ArteInvalida, match="TODO"):
        render_arte.validar(a)
    a = _arte("post", ["1080x1080"], 1); a["alt_text"] = ""
    with pytest.raises(render_arte.ArteInvalida, match="alt_text"):
        render_arte.validar(a)
    render_arte.validar(_arte("carrossel", ["1080x1350"], 6))


@precisa_chromium
@pytest.mark.parametrize("template,fmt,n", [("post", "1080x1080", 1), ("carrossel", "1080x1350", 3), ("story", "1080x1920", 1)])
def test_renderiza_nos_tres_formatos(raiz, template, fmt, n):
    (raiz / "templates").symlink_to(render_arte.RAIZ / "templates")
    pasta = _grava(raiz, _arte(template, [fmt], n))
    pngs = render_arte.renderizar(pasta, raiz)
    assert len(pngs) == n
    w, h = (int(x) for x in fmt.split("x"))
    for p in pngs:
        assert render_arte.dimensoes_png(p) == (w, h) and p.stat().st_size > 5000
    assert (pasta / "alt_text.txt").read_text().strip() == "Arte de teste."


@precisa_chromium
def test_servico_http_renderiza_e_valida(raiz):
    (raiz / "templates").symlink_to(render_arte.RAIZ / "templates")
    srv = render_servico.criar_servidor("127.0.0.1", 0, raiz, "segredo")
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        _grava(raiz, _arte("post", ["1080x1080"], 1))
        def post(body, token="segredo"):
            req = request.Request(f"http://127.0.0.1:{port}/render", data=json.dumps(body).encode(), method="POST",
                                  headers={"Content-Type": "application/json", "X-Agencia-Token": token})
            try:
                with request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except request.HTTPError as e:
                return e.code, json.loads(e.read())
        assert post({"peca": "2026-09-30_x"}, token="errado")[0] == 401
        code, d = post({"peca": "2026-09-30_x"})
        assert code == 200 and d["pngs"] == ["arte_01.png"]
        _grava(raiz, _arte("story", ["1080x1080"], 1), "2026-09-30_y")
        code, d = post({"peca": "2026-09-30_y"})
        assert code == 422 and "incompat" in d["erro"]
        with request.urlopen(f"http://127.0.0.1:{port}/saude") as r:
            assert json.loads(r.read())["ok"] is True
    finally:
        srv.shutdown()
