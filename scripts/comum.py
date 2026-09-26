"""Utilidades compartilhadas: raiz, config, logging, aprovadores."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent


def agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def carregar_config(raiz: Path = RAIZ) -> dict:
    with open(raiz / "config" / "agencia.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def carregar_env(raiz: Path = RAIZ) -> dict:
    """Lê .env (chave=valor) sem exportar e sem imprimir. Variáveis de ambiente já definidas vencem."""
    valores = {}
    p = raiz / ".env"
    if p.exists():
        for linha in p.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            k, v = linha.split("=", 1)
            valores[k.strip()] = v.strip().strip('"').strip("'")
    valores.update({k: v for k, v in os.environ.items() if k.startswith("AGENCIA_")})
    return valores


def aprovadores_ids(config: dict) -> set[int]:
    return {int(a["telegram_id"]) for a in config.get("aprovadores", []) if int(a.get("telegram_id", 0)) > 0}


def caminho_db(config: dict, raiz: Path = RAIZ) -> Path:
    return raiz / config["caminhos"]["db"]


def logger(nome: str, raiz: Path = RAIZ) -> logging.Logger:
    log = logging.getLogger(nome)
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    (raiz / "logs").mkdir(exist_ok=True)
    fh = logging.FileHandler(raiz / "logs" / f"{nome}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log
