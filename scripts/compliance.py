#!/usr/bin/env python3
"""Gate de compliance: camada determinística (compliance_regras) + camada LLM (especialista compliance).

Regra de combinação: a camada LLM só pode endurecer. Se as regras dizem REPROVADO, o resultado é
REPROVADO; se dizem ESCALAR, o LLM pode virar REPROVADO mas nunca APROVADO_COMPLIANCE. Sem LLM
(`--sem-llm`), REPROVADO e ESCALAR das regras valem; "aprovado" das regras vira ESCALAR, porque a
camada determinística sozinha nunca aprova (itens 3, 6 e 8 dependem do LLM). O gate nunca é pulado.

Funções: avaliar_regras (grava compliance_regras.json) → finalizar (combina e grava compliance.json).
avaliar_peca faz os dois com um cliente direto (ou só regras se cliente=None).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compliance_regras  # noqa: E402
import db  # noqa: E402
import especialista  # noqa: E402
from comum import RAIZ, agora_iso, caminho_db, carregar_config  # noqa: E402

ORDEM = {"REPROVADO": 2, "ESCALAR": 1, "APROVADO_COMPLIANCE": 0}
SEM_LLM = "camada LLM não executada: as regras sozinhas nunca aprovam"


def _normalizar_trechos(itens) -> list[str]:
    """O LLM às vezes devolve trechos como objetos JSON; tudo vira string única e sem repetição.
    (Bug encontrado na VPS em 26/09: dict.fromkeys estourava com dict — e o join do motivo também.)"""
    saida: list[str] = []
    for item in itens or []:
        if isinstance(item, str):
            txt = item.strip()
        elif isinstance(item, dict):
            txt = item.get("trecho") or item.get("texto") or json.dumps(item, ensure_ascii=False, sort_keys=True)
        else:
            txt = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if txt and txt not in saida:
            saida.append(txt)
    return saida


def texto_da_peca(pasta: Path) -> str:
    partes = []
    for arq in ("copy.md", "arte.yaml"):
        p = pasta / arq
        if p.exists():
            partes.append(p.read_text(encoding="utf-8"))
    if not partes:
        raise FileNotFoundError(f"{pasta}: sem copy.md nem arte.yaml para avaliar")
    return "\n".join(partes)


def combinar(regras: dict, llm: dict | None) -> dict:
    if not llm:
        saida = dict(regras)
        saida["resultado_regras"] = regras["resultado"]
        saida["trechos_problematicos"] = _normalizar_trechos(regras["trechos_problematicos"])
        saida["recomendacao_ao_redator"] = "; ".join(saida["trechos_problematicos"])
        saida["camadas"] = ["regras"]
        if saida["resultado"] == "APROVADO_COMPLIANCE":     # bug de 26/09: --sem-llm aprovava sozinho
            saida["resultado"] = "ESCALAR"
            saida["motivo_escalar"] = "; ".join(m for m in (regras.get("motivo_escalar", ""), SEM_LLM) if m)
        return saida
    itens = []
    for r, l in zip(regras["itens"], llm.get("itens") or regras["itens"]):
        if r["status"] == "falha":
            itens.append(r)                      # regra objetiva nunca é revertida pelo LLM
        elif l.get("status") == "falha":
            itens.append(l)
        else:
            itens.append(l if l.get("justificativa") else r)
    res_llm = llm.get("resultado", "ESCALAR")
    resultado = max(regras["resultado"], res_llm if res_llm in ORDEM else "ESCALAR", key=lambda x: ORDEM[x])
    trechos = _normalizar_trechos(list(regras["trechos_problematicos"]) + list(llm.get("trechos_problematicos") or []))
    motivos = "; ".join(m for m in (regras.get("motivo_escalar", ""), llm.get("motivo_escalar", "")) if m)
    return {"itens": itens, "resultado": resultado, "resultado_regras": regras["resultado"],
            "trechos_problematicos": trechos, "recomendacao_ao_redator": llm.get("recomendacao_ao_redator", ""),
            "motivo_escalar": motivos, "camadas": ["regras", "llm"]}


def _pago(pasta: Path) -> bool:
    peca = yaml.safe_load((pasta / "peca.yaml").read_text(encoding="utf-8"))
    return peca.get("canal") in ("google_ads", "meta_ads") or peca.get("formato") == "anuncio"


def avaliar_regras(peca_id: str, *, raiz: Path) -> dict:
    pasta = raiz / "conteudo" / peca_id
    regras = compliance_regras.avaliar(texto_da_peca(pasta), raiz / "brand", pago=_pago(pasta))
    (pasta / "compliance_regras.json").write_text(json.dumps(regras, ensure_ascii=False, indent=2), encoding="utf-8")
    return regras


def finalizar(peca_id: str, *, raiz: Path, llm: dict | None) -> dict:
    pasta = raiz / "conteudo" / peca_id
    regras = json.loads((pasta / "compliance_regras.json").read_text(encoding="utf-8"))
    final = combinar(regras, llm)
    final.update({"peca": peca_id, "avaliado_em": agora_iso(), "pago": _pago(pasta)})
    (pasta / "compliance.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    return final


def contexto_llm(regras: dict) -> str:
    return "Resultado da camada determinística (não reverta 'falha'):\n" + json.dumps(regras, ensure_ascii=False, indent=1)


def avaliar_peca(peca_id: str, *, raiz: Path, con, cliente=None, config: dict | None = None) -> dict:
    """Modo direto ou só regras."""
    config = config or carregar_config(raiz)
    regras = avaliar_regras(peca_id, raiz=raiz)
    llm = None
    if cliente is not None:
        pasta = raiz / "conteudo" / peca_id
        p = especialista.executar("compliance", raiz=raiz, con=con, cliente=cliente, peca_id=peca_id,
                                  contexto_extra=contexto_llm(regras), config=config, saida=pasta / "compliance_llm.json")
        llm = json.loads(p.read_text(encoding="utf-8"))
    return finalizar(peca_id, raiz=raiz, llm=llm)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--peca", required=True)
    ap.add_argument("--sem-llm", action="store_true")
    ap.add_argument("--raiz", default=str(RAIZ))
    a = ap.parse_args(argv)
    raiz = Path(a.raiz)
    config = carregar_config(raiz)
    con = db.inicializar(caminho_db(config, raiz))
    cliente = None if a.sem_llm else especialista.cliente_padrao(raiz)
    if cliente is None and not a.sem_llm:
        print("sem endpoint direto: avaliando só as regras (a camada LLM roda pelo pipeline.py passo/entregar)")
    r = avaliar_peca(a.peca, raiz=raiz, con=con, cliente=cliente, config=config)
    print(f"{a.peca}: {r['resultado']} (regras: {r['resultado_regras']}) | trechos: {r['trechos_problematicos']} | escalar: {r['motivo_escalar']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
