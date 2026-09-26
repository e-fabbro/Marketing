#!/usr/bin/env python3
"""Serviço de render NO HOST (D5), no molde do estúdio de reels: HTTP em 127.0.0.1, um render por vez.
O container do DUDS (--network host) chama POST /render {"peca": "<id>"}; o serviço lê e grava na mesma
pasta (bind mount). Token simples em AGENCIA_RENDER_TOKEN (.env) no header X-Agencia-Token.

  python3 scripts/render_servico.py [--host 127.0.0.1] [--port 8766]
GET /saude → {"ok": true, "chromium": "..."}
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_arte  # noqa: E402
from comum import RAIZ, carregar_env, logger  # noqa: E402

LOCK = threading.Lock()


def criar_servidor(host: str, port: int, raiz: Path, token: str) -> ThreadingHTTPServer:
    log = logger("render_servico", raiz)

    class H(BaseHTTPRequestHandler):
        def _json(self, code: int, obj: dict) -> None:
            corpo = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def _auth(self) -> bool:
            return not token or self.headers.get("X-Agencia-Token", "") == token

        def do_GET(self):  # noqa: N802
            if self.path == "/saude":
                try:
                    return self._json(200, {"ok": True, "chromium": render_arte.encontrar_chromium()})
                except RuntimeError as exc:
                    return self._json(500, {"ok": False, "erro": str(exc)})
            self._json(404, {"erro": "rota"})

        def do_POST(self):  # noqa: N802
            if not self._auth():
                return self._json(401, {"erro": "token"})
            if self.path != "/render":
                return self._json(404, {"erro": "rota"})
            n = int(self.headers.get("Content-Length", "0"))
            try:
                dados = json.loads(self.rfile.read(n) or b"{}")
                peca = dados["peca"]
                if "/" in peca or ".." in peca:
                    raise ValueError("id de peça inválido")
                pasta = raiz / "conteudo" / peca
                with LOCK:                       # um render por vez (RAM do host)
                    pngs = render_arte.renderizar(pasta, raiz)
                self._json(200, {"ok": True, "pngs": [p.name for p in pngs]})
            except render_arte.ArteInvalida as exc:
                self._json(422, {"ok": False, "erro": f"arte.yaml: {exc}"})
            except Exception as exc:  # noqa: BLE001
                log.error("render falhou: %s", exc)
                self._json(500, {"ok": False, "erro": str(exc)})

        def log_message(self, fmt, *args):  # silencia o log padrão; usamos o nosso
            log.info("%s %s", self.address_string(), fmt % args)

    return ThreadingHTTPServer((host, port), H)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8766)
    a = ap.parse_args()
    token = carregar_env(RAIZ).get("AGENCIA_RENDER_TOKEN", "")
    srv = criar_servidor(a.host, a.port, RAIZ, token)
    logger("render_servico").info("render_servico em http://%s:%d (token %s)", a.host, a.port, "sim" if token else "não")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
