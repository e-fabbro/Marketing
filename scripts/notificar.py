#!/usr/bin/env python3
"""Envia texto ao grupo de aprovação pelo bot da agência (só sendMessage: não conflita com o polling do bot).
  notificar.py --texto "..."   |   echo "..." | notificar.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import RAIZ, carregar_config, carregar_env, logger  # noqa: E402


def enviar(texto: str, raiz: Path = RAIZ, http=None) -> bool:
    env, config = carregar_env(raiz), carregar_config(raiz)
    token = env.get("AGENCIA_TELEGRAM_BOT_TOKEN")
    chat = env.get("AGENCIA_TELEGRAM_CHAT_ID") or config.get("telegram", {}).get("grupo_marketing_chat_id")
    if not token or not chat:
        logger("notificar", raiz).error("sem token ou chat_id; mensagem não enviada: %s", texto[:80])
        return False
    if http is None:
        import requests
        http = requests.post
    r = http(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": int(chat), "text": texto[:4000]}, timeout=30)
    ok = getattr(r, "status_code", 500) == 200
    (logger("notificar", raiz).info if ok else logger("notificar", raiz).error)("enviado=%s %s", ok, texto[:60])
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--texto")
    a = ap.parse_args()
    texto = a.texto if a.texto is not None else sys.stdin.read()
    return 0 if enviar(texto.strip()) else 1


if __name__ == "__main__":
    sys.exit(main())
