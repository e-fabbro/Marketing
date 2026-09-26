#!/usr/bin/env python3
"""Máquina de estados do pipeline. Toda mudança de estado passa por aqui.

Uso:
  python3 scripts/transicao.py criar --id 2026-09-29_slug --canal instagram --formato carrossel \
      --pilar 2 --objetivo salvamentos --cta "Salve" --autor estrategista
  python3 scripts/transicao.py mover --peca 2026-09-29_slug --para RASCUNHO --autor redator [--motivo "..."]
  python3 scripts/transicao.py estado --peca 2026-09-29_slug

Transição inválida = exceção TransicaoInvalida e código de saída 2. Nunca silêncio.
APROVADO / AJUSTAR / DESCARTADO (a partir de AGUARDANDO_HUMANO) e qualquer saída de ESCALAR exigem
autor "telegram:<id>" com id em config/agencia.yaml -> aprovadores.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
from comum import RAIZ, agora_iso, aprovadores_ids, caminho_db, carregar_config  # noqa: E402

TRANSICOES: dict[str | None, set[str]] = {
    None: {"PAUTA"},
    "PAUTA": {"RASCUNHO", "DESCARTADO"},
    "RASCUNHO": {"ARTE", "DESCARTADO"},
    "ARTE": {"COMPLIANCE"},
    "COMPLIANCE": {"APROVADO_COMPLIANCE", "REPROVADO", "ESCALAR"},
    "APROVADO_COMPLIANCE": {"AGUARDANDO_HUMANO"},
    "REPROVADO": {"RASCUNHO", "ESCALAR"},
    "ESCALAR": {"RASCUNHO", "DESCARTADO", "AGUARDANDO_HUMANO"},
    "AGUARDANDO_HUMANO": {"APROVADO", "AJUSTAR", "DESCARTADO"},
    "APROVADO": {"AGENDADO"},
    "AJUSTAR": {"RASCUNHO"},
    "AGENDADO": {"PUBLICADO", "DESCARTADO"},
    "PUBLICADO": {"MEDIDO"},
    "MEDIDO": set(),
    "DESCARTADO": set(),
}

EXIGEM_APROVADOR: set[tuple[str, str]] = {
    ("AGUARDANDO_HUMANO", "APROVADO"), ("AGUARDANDO_HUMANO", "AJUSTAR"), ("AGUARDANDO_HUMANO", "DESCARTADO"),
    ("ESCALAR", "RASCUNHO"), ("ESCALAR", "DESCARTADO"), ("ESCALAR", "AGUARDANDO_HUMANO"),
}


class TransicaoInvalida(Exception):
    pass


def _autor_e_aprovador(autor: str, config: dict) -> bool:
    if not autor.startswith("telegram:"):
        return False
    try:
        return int(autor.split(":", 1)[1]) in aprovadores_ids(config)
    except ValueError:
        return False


def _peca_yaml(raiz: Path, peca: dict) -> Path:
    return raiz / peca["pasta"] / "peca.yaml"


def _gravar_historico(raiz: Path, peca: dict, de: str | None, para: str, autor: str, motivo: str | None) -> None:
    p = _peca_yaml(raiz, peca)
    p.parent.mkdir(parents=True, exist_ok=True)
    dados = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    dados.update({k: peca[k] for k in ("id", "canal", "formato", "pilar", "objetivo", "cta")})
    dados["estado"] = para
    dados.setdefault("historico", []).append(
        {"de": de, "para": para, "autor": autor, "motivo": motivo or "", "timestamp": agora_iso()}
    )
    p.write_text(yaml.safe_dump(dados, allow_unicode=True, sort_keys=False), encoding="utf-8")


def criar_peca(con, raiz: Path, *, id: str, canal: str, formato: str, pilar: str, objetivo: str, cta: str,
               autor: str, motivo: str | None = None, extras: dict | None = None) -> dict:
    if con.execute("SELECT 1 FROM pecas WHERE id=?", (id,)).fetchone():
        raise TransicaoInvalida(f"peça {id} já existe")
    pasta = f"conteudo/{id}"
    con.execute(
        "INSERT INTO pecas (id, canal, formato, pilar, objetivo, cta, estado, pasta) VALUES (?,?,?,?,?,?,?,?)",
        (id, canal, formato, str(pilar), objetivo, cta, "PAUTA", pasta),
    )
    con.execute("INSERT INTO transicoes (peca_id, de, para, autor, motivo) VALUES (?,?,?,?,?)",
                (id, None, "PAUTA", autor, motivo))
    con.commit()
    peca = dict(con.execute("SELECT * FROM pecas WHERE id=?", (id,)).fetchone())
    _gravar_historico(raiz, peca, None, "PAUTA", autor, motivo)
    if extras:
        p = _peca_yaml(raiz, peca)
        dados = yaml.safe_load(p.read_text(encoding="utf-8"))
        for k, v in extras.items():
            dados.setdefault(k, v)
        p.write_text(yaml.safe_dump(dados, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return peca


def mover(con, raiz: Path, peca_id: str, para: str, autor: str, motivo: str | None = None,
          config: dict | None = None) -> dict:
    config = config or carregar_config(raiz)
    row = con.execute("SELECT * FROM pecas WHERE id=?", (peca_id,)).fetchone()
    if not row:
        raise TransicaoInvalida(f"peça {peca_id} não existe")
    peca = dict(row)
    de = peca["estado"]
    if para not in db.ESTADOS:
        raise TransicaoInvalida(f"estado desconhecido: {para}")
    if para not in TRANSICOES.get(de, set()):
        raise TransicaoInvalida(f"{peca_id}: {de} -> {para} não é permitido")
    if (de, para) in EXIGEM_APROVADOR and not _autor_e_aprovador(autor, config):
        raise TransicaoInvalida(f"{peca_id}: {de} -> {para} exige autor telegram:<id> de aprovador; recebido '{autor}'")
    max_voltas = int(config.get("compliance", {}).get("max_voltas", 2))
    voltas = int(peca["voltas_compliance"])
    if de == "COMPLIANCE" and para == "REPROVADO":
        voltas += 1
    if de == "REPROVADO" and para == "RASCUNHO" and voltas > max_voltas:
        raise TransicaoInvalida(
            f"{peca_id}: {voltas}ª reprovação excede max_voltas={max_voltas}; use ESCALAR (decisão humana)")
    con.execute("UPDATE pecas SET estado=?, voltas_compliance=?, atualizado_em=? WHERE id=?",
                (para, voltas, agora_iso(), peca_id))
    con.execute("INSERT INTO transicoes (peca_id, de, para, autor, motivo) VALUES (?,?,?,?,?)",
                (peca_id, de, para, autor, motivo))
    con.commit()
    peca["estado"], peca["voltas_compliance"] = para, voltas
    _gravar_historico(raiz, peca, de, para, autor, motivo)
    return peca


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raiz", default=str(RAIZ))
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("criar")
    for k in ("id", "canal", "formato", "pilar", "objetivo", "cta", "autor"):
        c.add_argument(f"--{k}", required=True)
    c.add_argument("--motivo")
    m = sub.add_parser("mover")
    m.add_argument("--peca", required=True); m.add_argument("--para", required=True)
    m.add_argument("--autor", required=True); m.add_argument("--motivo")
    e = sub.add_parser("estado"); e.add_argument("--peca", required=True)
    a = ap.parse_args(argv)
    raiz = Path(a.raiz)
    config = carregar_config(raiz)
    con = db.inicializar(caminho_db(config, raiz))
    try:
        if a.cmd == "criar":
            p = criar_peca(con, raiz, id=a.id, canal=a.canal, formato=a.formato, pilar=a.pilar,
                           objetivo=a.objetivo, cta=a.cta, autor=a.autor, motivo=a.motivo)
            print(f"ok: {p['id']} -> PAUTA")
        elif a.cmd == "mover":
            p = mover(con, raiz, a.peca, a.para, a.autor, a.motivo, config)
            print(f"ok: {p['id']} -> {p['estado']} (voltas_compliance={p['voltas_compliance']})")
        else:
            r = con.execute("SELECT id, estado, voltas_compliance, atualizado_em FROM pecas WHERE id=?", (a.peca,)).fetchone()
            print(dict(r) if r else f"peça {a.peca} não existe")
    except TransicaoInvalida as exc:
        print(f"ERRO transição: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
