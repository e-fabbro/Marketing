#!/usr/bin/env python3
"""Motor de passos do pipeline: ESTRATEGISTA → REDATOR → DESIGNER (arte.yaml + render) → COMPLIANCE
(regras + LLM) → fila humana, com estado via transicao.py.

Modo delegação (padrão, D1c — o DUDS opera):
  passo    --peca <id>                     faz tudo que é determinístico e para na 1ª delegação necessária;
                                           imprime JSON {"acao":"delegar","especialista":...,"prompt":...}
                                           ou {"acao":"fim","estado":...}
  entregar --peca <id> --arquivo <resp>    recebe a resposta do subagente, valida, grava, e chama `passo`
  pauta    --semana AAAA-MM-DD             imprime a delegação do ESTRATEGISTA
  entregar --pauta AAAA-MM-DD --arquivo <resp> [--criar]   grava pauta_<semana>.yaml e cria as peças

Modo direto (se AGENCIA_LLM_BASE_URL no .env): `peca --peca <id>` e `pauta --semana X --criar` rodam tudo.
Erros sobem como exceção (código 1). Nada aqui fala com humanos.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compliance  # noqa: E402
import db  # noqa: E402
import especialista  # noqa: E402
import render_arte  # noqa: E402
import render_cliente  # noqa: E402
import transicao  # noqa: E402
from comum import RAIZ, agora_iso, caminho_db, carregar_config, logger  # noqa: E402

ETAPAS_VAZIAS = {"rodada": 0, "redator": False, "designer": False, "render": None, "designer_tentativas": 0,
                 "designer_erro": "", "compliance_llm": False, "pendente": None}


def _pasta(raiz: Path, peca_id: str) -> Path:
    return raiz / "conteudo" / peca_id


def _ler_etapas(pasta: Path) -> dict:
    p = pasta / "etapas.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else dict(ETAPAS_VAZIAS)


def _gravar_etapas(pasta: Path, et: dict) -> None:
    (pasta / "etapas.json").write_text(json.dumps(et, ensure_ascii=False, indent=2), encoding="utf-8")


def _nova_rodada(pasta: Path, et: dict) -> dict:
    novo = dict(ETAPAS_VAZIAS)
    novo["rodada"] = int(et.get("rodada", 0)) + 1
    _gravar_etapas(pasta, novo)
    return novo


def _estado(con, peca_id: str) -> str:
    r = con.execute("SELECT estado FROM pecas WHERE id=?", (peca_id,)).fetchone()
    if not r:
        raise transicao.TransicaoInvalida(f"peça {peca_id} não existe")
    return r[0]


def _delegar(pasta: Path, et: dict, nome: str, prep: dict) -> dict:
    et["pendente"] = {"especialista": nome, "prompt": str(prep["prompt"]), "emitido_em": agora_iso(),
                      "modelo": prep["modelo"], "saida": prep["saida"]}
    _gravar_etapas(pasta, et)
    return {"acao": "delegar", "especialista": nome, "modelo": prep["modelo"], "prompt": str(prep["prompt"]),
            "saida_esperada": prep["saida"],
            "instrucao": f"delegate_task(goal='Executar a skill {nome.upper()} da Agência REVERA e devolver só o bloco pedido', "
                         f"context=<conteúdo de {prep['prompt'].name}>) → salve a resposta em resposta_{nome}.md e rode "
                         f"pipeline.py entregar --peca {pasta.name} --arquivo {pasta / f'resposta_{nome}.md'}"}


def _contexto_redator(pasta: Path) -> str:
    ctx = ""
    if (pasta / "compliance.json").exists():
        ctx += "Parecer de compliance anterior (corrija tudo que falhou):\n" + (pasta / "compliance.json").read_text(encoding="utf-8")
    if (pasta / "ajuste.md").exists():
        ctx += "\nPedido de ajuste do humano:\n" + (pasta / "ajuste.md").read_text(encoding="utf-8")
    return ctx


def _contexto_designer(con, peca_id: str, et: dict) -> str:
    formato = con.execute("SELECT formato FROM pecas WHERE id=?", (peca_id,)).fetchone()[0]
    ctx = f"Templates disponíveis: {', '.join(render_arte.FORMATOS_POR_TEMPLATE)}. Formato da peça: {formato}."
    if et.get("designer_erro"):
        ctx += f"\nERRO na tentativa anterior: {et['designer_erro']}. Corrija."
    return ctx


def proximo_passo(peca_id: str, *, raiz: Path, con, config: dict) -> dict:
    """Executa passos determinísticos até precisar de uma delegação ou chegar a um fim."""
    log = logger("pipeline", raiz)
    pasta = _pasta(raiz, peca_id)
    max_voltas = int(config["compliance"]["max_voltas"])
    while True:
        estado = _estado(con, peca_id)
        et = _ler_etapas(pasta)
        if et.get("pendente"):
            p = et["pendente"]
            return {"acao": "delegar", "especialista": p["especialista"], "modelo": p["modelo"], "prompt": p["prompt"],
                    "saida_esperada": p["saida"], "instrucao": f"delegação pendente desde {p['emitido_em']}; entregue a resposta com pipeline.py entregar"}
        if estado in ("PAUTA", "AJUSTAR", "REPROVADO"):
            transicao.mover(con, raiz, peca_id, "RASCUNHO", "duds", "pipeline: início da rodada", config)
            _nova_rodada(pasta, et)
            continue
        if estado == "RASCUNHO":
            if not et["redator"]:
                especialista.verificar_teto(con, "redator", config)
                return _delegar(pasta, et, "redator", especialista.preparar("redator", raiz=raiz, peca_id=peca_id, contexto_extra=_contexto_redator(pasta), config=config))
            if not et["designer"]:
                if et["designer_tentativas"] >= 2:
                    raise render_arte.ArteInvalida(f"{peca_id}: arte.yaml inválido após 2 tentativas: {et['designer_erro']}")
                especialista.verificar_teto(con, "designer", config)
                return _delegar(pasta, et, "designer", especialista.preparar("designer", raiz=raiz, peca_id=peca_id, contexto_extra=_contexto_designer(con, peca_id, et), config=config))
            if not et["render"]:
                try:
                    et["render"] = render_cliente.renderizar_peca(peca_id, raiz)
                except render_arte.ArteInvalida as exc:
                    et.update({"designer": False, "designer_tentativas": et["designer_tentativas"] + 1, "designer_erro": str(exc)})
                    _gravar_etapas(pasta, et)
                    log.warning("%s arte inválida (tentativa %d): %s", peca_id, et["designer_tentativas"], exc)
                    continue
                _gravar_etapas(pasta, et)
            transicao.mover(con, raiz, peca_id, "ARTE", "designer", f"arte renderizada: {', '.join(et['render'])}", config)
            continue
        if estado == "ARTE":
            transicao.mover(con, raiz, peca_id, "COMPLIANCE", "duds", "gate obrigatório", config)
            continue
        if estado == "COMPLIANCE":
            regras = compliance.avaliar_regras(peca_id, raiz=raiz)
            llm = None
            if regras["resultado"] != "REPROVADO":
                if not et["compliance_llm"]:
                    especialista.verificar_teto(con, "compliance", config)
                    return _delegar(pasta, et, "compliance", especialista.preparar("compliance", raiz=raiz, peca_id=peca_id, contexto_extra=compliance.contexto_llm(regras), config=config))
                llm = json.loads((pasta / "compliance_llm.json").read_text(encoding="utf-8"))
            parecer = compliance.finalizar(peca_id, raiz=raiz, llm=llm)
            resultado = parecer["resultado"]
            peca = transicao.mover(con, raiz, peca_id, resultado, "compliance", parecer.get("motivo_escalar") or "; ".join(parecer["trechos_problematicos"]) or "ok", config)
            log.info("%s compliance=%s voltas=%s rodada=%s", peca_id, resultado, peca["voltas_compliance"], et["rodada"])
            if resultado == "APROVADO_COMPLIANCE":
                transicao.mover(con, raiz, peca_id, "AGUARDANDO_HUMANO", "duds", "pronto para aprovação humana", config)
                return {"acao": "fim", "estado": "AGUARDANDO_HUMANO", "detalhe": "o bot de aprovação envia ao grupo"}
            if resultado == "ESCALAR":
                return {"acao": "fim", "estado": "ESCALAR", "detalhe": parecer.get("motivo_escalar", "")}
            if peca["voltas_compliance"] > max_voltas:
                transicao.mover(con, raiz, peca_id, "ESCALAR", "duds", f"{peca['voltas_compliance']}ª reprovação; decisão humana", config)
                return {"acao": "fim", "estado": "ESCALAR", "detalhe": "reprovações acima do limite"}
            continue   # REPROVADO → nova rodada
        return {"acao": "fim", "estado": estado, "detalhe": "o pipeline só atua de PAUTA até a fila humana"}


def entregar_resposta(peca_id: str, texto: str, *, raiz: Path, con, config: dict, tokens: tuple[int, int] | None = None) -> dict:
    pasta = _pasta(raiz, peca_id)
    et = _ler_etapas(pasta)
    pend = et.get("pendente")
    if not pend:
        raise RuntimeError(f"{peca_id}: nenhuma delegação pendente; rode `passo` primeiro")
    nome = pend["especialista"]
    saida = pasta / "compliance_llm.json" if nome == "compliance" else None
    prompt_chars = len(Path(pend["prompt"]).read_text(encoding="utf-8")) if Path(pend["prompt"]).exists() else 0
    try:
        especialista.entregar(nome, texto, raiz=raiz, con=con, peca_id=peca_id, saida=saida, config=config,
                              tokens=tokens, prompt_chars=prompt_chars, modelo=pend.get("modelo"))
    except (ValueError, yaml.YAMLError) as exc:      # json/yaml inválido: mantém pendente para nova tentativa
        raise RuntimeError(f"{peca_id}: resposta do {nome} inválida ({exc}); a delegação continua pendente") from exc
    et[nome if nome != "compliance" else "compliance_llm"] = True
    et["pendente"] = None
    _gravar_etapas(pasta, et)
    return proximo_passo(peca_id, raiz=raiz, con=con, config=config)


def processar_peca(peca_id: str, *, raiz: Path, con, cliente, config: dict, cliente_compliance="mesmo") -> str:
    """Modo direto: repete passo → chamada ao endpoint → entrega até um fim. Devolve o estado final."""
    cli_comp = cliente if cliente_compliance == "mesmo" else cliente_compliance
    r = proximo_passo(peca_id, raiz=raiz, con=con, config=config)
    while r["acao"] == "delegar":
        nome = r["especialista"]
        cli = cli_comp if nome == "compliance" else cliente
        if cli is None:                                   # sem LLM de compliance: só regras
            pasta = _pasta(raiz, peca_id); et = _ler_etapas(pasta)
            et["compliance_llm"], et["pendente"] = True, None
            (pasta / "compliance_llm.json").write_text("{}", encoding="utf-8")
            _gravar_etapas(pasta, et)
            r = proximo_passo(peca_id, raiz=raiz, con=con, config=config)
            continue
        cfg = config["especialistas"][nome]
        prep = especialista.preparar(nome, raiz=raiz, peca_id=peca_id, contexto_extra="", config=config)  # system atual
        # o user do prompt pendente já está no arquivo; reconstruímos a partir dele para o cliente direto
        texto_prompt = Path(r["prompt"]).read_text(encoding="utf-8")
        user = texto_prompt.split("# Entrada\n\n", 1)[1] if "# Entrada\n\n" in texto_prompt else texto_prompt
        resposta, t_in, t_out = cli.completar(cfg["modelo"], prep["system"], user, float(cfg["temperatura"]), int(cfg["max_tokens"]))
        r = entregar_resposta(peca_id, resposta, raiz=raiz, con=con, config=config, tokens=(t_in, t_out))
    return r["estado"]


# ---------- pauta ----------
def _contexto_pauta(raiz: Path, semana: str) -> str:
    anteriores = sorted((raiz / "conteudo").glob("pauta_*.yaml"))[-4:]
    ctx = [f"Semana alvo (segunda-feira): {semana}"]
    for p in anteriores:
        ctx.append(f"## Pauta anterior {p.name}\n{p.read_text(encoding='utf-8')}")
    return "\n".join(ctx)


def criar_pecas_da_pauta(pauta_path: Path, *, raiz: Path, con, autor: str = "estrategista") -> list[str]:
    pauta = yaml.safe_load(pauta_path.read_text(encoding="utf-8"))
    ids = []
    for p in pauta["pecas"]:
        transicao.criar_peca(con, raiz, id=p["id"], canal=p["canal"], formato=p["formato"], pilar=str(p["pilar"]),
                             objetivo=p["objetivo"], cta=p["cta"], autor=autor, motivo=f"pauta {pauta.get('semana')}",
                             extras={k: v for k, v in p.items() if k not in ("id", "canal", "formato", "pilar", "objetivo", "cta")})
        ids.append(p["id"])
    return ids


def gerar_pauta(semana: str, *, raiz: Path, con, cliente, config: dict, criar: bool) -> Path:
    """Modo direto."""
    saida = raiz / "conteudo" / f"pauta_{semana}.yaml"
    especialista.executar("estrategista", raiz=raiz, con=con, cliente=cliente, contexto_extra=_contexto_pauta(raiz, semana), saida=saida, config=config)
    if criar:
        criar_pecas_da_pauta(saida, raiz=raiz, con=con)
    return saida


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raiz", default=str(RAIZ))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("passo"); s.add_argument("--peca", required=True)
    s = sub.add_parser("entregar"); s.add_argument("--peca"); s.add_argument("--pauta"); s.add_argument("--arquivo", required=True); s.add_argument("--criar", action="store_true")
    s = sub.add_parser("pauta"); s.add_argument("--semana", required=True); s.add_argument("--criar", action="store_true")
    s = sub.add_parser("peca"); s.add_argument("--peca", required=True); s.add_argument("--sem-llm-compliance", action="store_true")
    a = ap.parse_args(argv)
    raiz = Path(a.raiz)
    config = carregar_config(raiz)
    con = db.inicializar(caminho_db(config, raiz))
    cliente = especialista.cliente_padrao(raiz)
    if a.cmd == "passo":
        print(json.dumps(proximo_passo(a.peca, raiz=raiz, con=con, config=config), ensure_ascii=False, indent=2))
    elif a.cmd == "entregar":
        texto = Path(a.arquivo).read_text(encoding="utf-8")
        if a.pauta:
            saida = raiz / "conteudo" / f"pauta_{a.pauta}.yaml"
            especialista.entregar("estrategista", texto, raiz=raiz, con=con, saida=saida, config=config,
                                  prompt_chars=len(especialista.montar_system("estrategista", raiz)))
            ids = criar_pecas_da_pauta(saida, raiz=raiz, con=con) if a.criar else []
            print(json.dumps({"acao": "fim", "pauta": str(saida), "pecas_criadas": ids}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(entregar_resposta(a.peca, texto, raiz=raiz, con=con, config=config), ensure_ascii=False, indent=2))
    elif a.cmd == "pauta":
        if cliente is None:
            prep = especialista.preparar("estrategista", raiz=raiz, contexto_extra=_contexto_pauta(raiz, a.semana), config=config,
                                         pasta_prompt=raiz / "conteudo")
            print(json.dumps({"acao": "delegar", "especialista": "estrategista", "modelo": prep["modelo"], "prompt": str(prep["prompt"]),
                              "instrucao": f"delegate_task com o conteúdo do prompt; depois pipeline.py entregar --pauta {a.semana} --arquivo <resposta> --criar"}, ensure_ascii=False, indent=2))
        else:
            print(f"ok: {gerar_pauta(a.semana, raiz=raiz, con=con, cliente=cliente, config=config, criar=a.criar)}")
    else:
        if cliente is None:
            print("sem AGENCIA_LLM_BASE_URL: use `passo` / `entregar` (modo delegação)", file=sys.stderr)
            return 1
        print(f"{a.peca}: {processar_peca(a.peca, raiz=raiz, con=con, cliente=cliente, config=config, cliente_compliance=None if a.sem_llm_compliance else 'mesmo')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
