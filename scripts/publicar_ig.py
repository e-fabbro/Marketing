#!/usr/bin/env python3
"""PUBLICADOR (sem LLM): agenda e publica no Instagram peças APROVADAS, e mede no dia seguinte.

  publicar_ig.py agendar --peca <id> --quando "AAAA-MM-DD HH:MM"   (hora local do config) APROVADO → AGENDADO
  publicar_ig.py cancelar --peca <id>                              AGENDADO → DESCARTADO (por telegram:<id> aprovador)
  publicar_ig.py tick                                              publica o que venceu (cron a cada 5 min, Fase 6)
  publicar_ig.py medir                                             insights das peças PUBLICADAS há ≥ 20 h → metricas → MEDIDO
  publicar_ig.py conta                                             insights da conta (seguidores, alcance do dia) → metricas
  publicar_ig.py testar                                            GET /me e /{ig_user}?fields=username (sem publicar)

Regras duras: só publica peça em AGENDADO cujo histórico tenha APROVAR em `aprovacoes` por aprovador; nunca
inventa métrica; falha de publicação fica em `agendamentos.erro` e a peça permanece AGENDADO (máx. 3 tentativas
→ FALHOU e alerta). A API do Instagram só aceita imagem por URL pública: as PNGs são copiadas para
AGENCIA_MIDIA_DIR (servido pelo nginx) com nome aleatório.

.env: AGENCIA_IG_TOKEN, AGENCIA_IG_USER_ID, AGENCIA_MIDIA_DIR, AGENCIA_MIDIA_BASE_URL, AGENCIA_GRAPH_VERSION (v23.0)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import secrets
import shutil
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db  # noqa: E402
import transicao  # noqa: E402
from comum import RAIZ, agora_iso, caminho_db, carregar_config, carregar_env, logger  # noqa: E402

LIMITE_LEGENDA = 2200
MAX_TENTATIVAS = 3
METRICAS_MIDIA = ("reach", "saved", "shares", "comments", "likes")
NOME_METRICA = {"reach": "alcance", "saved": "salvamentos", "shares": "compartilhamentos", "comments": "comentarios", "likes": "curtidas"}


class ErroPublicacao(Exception):
    pass


class GraphClient:
    """Cliente mínimo da Graph API. Token nunca é logado."""

    def __init__(self, token: str, versao: str = "v23.0"):
        self.token, self.base = token, f"https://graph.facebook.com/{versao}"

    def _req(self, metodo: str, caminho: str, **params):
        import requests
        params["access_token"] = self.token
        r = requests.request(metodo, f"{self.base}/{caminho.lstrip('/')}", params=params if metodo == "GET" else None,
                             data=params if metodo != "GET" else None, timeout=60)
        try:
            d = r.json()
        except ValueError:
            d = {"error": {"message": r.text[:300]}}
        if r.status_code >= 400 or "error" in d:
            e = d.get("error", {})
            raise ErroPublicacao(f"Graph {r.status_code}: {e.get('message', '?')} (code {e.get('code')}, sub {e.get('error_subcode')})")
        return d

    def get(self, caminho: str, **params):
        return self._req("GET", caminho, **params)

    def post(self, caminho: str, **params):
        return self._req("POST", caminho, **params)


def cliente_padrao(raiz: Path = RAIZ) -> GraphClient:
    env = carregar_env(raiz)
    if not env.get("AGENCIA_IG_TOKEN"):
        raise ErroPublicacao("AGENCIA_IG_TOKEN ausente no .env (P3)")
    return GraphClient(env["AGENCIA_IG_TOKEN"], env.get("AGENCIA_GRAPH_VERSION", "v23.0"))


def montar_legenda(copy_md: str) -> str:
    """Gancho + Corpo (sem cabeçalhos de slide) + CTA + Assinatura + Hashtags, ≤ 2200 caracteres."""
    secoes = {}
    atual = None
    for linha in copy_md.splitlines():
        m = re.match(r"^## (.+)$", linha)
        if m:
            atual = m.group(1).strip().lower()
            secoes[atual] = []
        elif atual and not linha.startswith("# "):
            secoes[atual].append(linha)
    def sec(nome):
        txt = "\n".join(secoes.get(nome, [])).strip()
        return re.sub(r"^###\s+.*$", "", txt, flags=re.M).strip()
    partes = [sec("gancho"), sec("corpo"), sec("cta"), sec("assinatura"), sec("hashtags")]
    if not partes[3] or "crm" not in partes[3].lower():
        raise ErroPublicacao("copy.md sem seção Assinatura com CRM")
    legenda = "\n\n".join(p for p in partes if p)
    legenda = re.sub(r"\n{3,}", "\n\n", legenda)
    if len(legenda) > LIMITE_LEGENDA:
        raise ErroPublicacao(f"legenda com {len(legenda)} caracteres (máx. {LIMITE_LEGENDA})")
    return legenda


def publicar_midia(arquivos: list[Path], raiz: Path) -> list[str]:
    """Copia as PNGs para o diretório público com nome aleatório e devolve as URLs."""
    env = carregar_env(raiz)
    pasta = Path(env.get("AGENCIA_MIDIA_DIR") or (raiz / "midia_publica"))
    base = (env.get("AGENCIA_MIDIA_BASE_URL") or "").rstrip("/")
    if not base:
        raise ErroPublicacao("AGENCIA_MIDIA_BASE_URL ausente no .env (URL pública servida pelo nginx)")
    pasta.mkdir(parents=True, exist_ok=True)
    urls = []
    for a in arquivos:
        nome = f"{secrets.token_urlsafe(18)}.png"
        shutil.copy2(a, pasta / nome)
        urls.append(f"{base}/{nome}")
    return urls


def _aprovada(con, peca_id: str) -> bool:
    return con.execute("SELECT 1 FROM aprovacoes WHERE peca_id=? AND decisao='APROVAR'", (peca_id,)).fetchone() is not None


def agendar(con, raiz: Path, peca_id: str, quando_local: str, config: dict) -> dict:
    if not _aprovada(con, peca_id):
        raise transicao.TransicaoInvalida(f"{peca_id}: sem APROVAR registrado em aprovacoes; não agenda")
    tz = ZoneInfo(config.get("fuso", "America/Sao_Paulo"))
    local = dt.datetime.strptime(quando_local, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    quando_utc = local.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    peca = transicao.mover(con, raiz, peca_id, "AGENDADO", "publicador", f"agendado para {quando_local} ({quando_utc})", config)
    con.execute("INSERT INTO agendamentos (peca_id, canal, quando_utc) VALUES (?,?,?)", (peca_id, peca["canal"], quando_utc))
    con.commit()
    return {"peca": peca_id, "quando_utc": quando_utc, "estado": "AGENDADO"}


def cancelar(con, raiz: Path, peca_id: str, autor: str, config: dict) -> str:
    con.execute("UPDATE agendamentos SET status='CANCELADO' WHERE peca_id=? AND status='AGENDADO'", (peca_id,))
    return transicao.mover(con, raiz, peca_id, "DESCARTADO", autor, "agendamento cancelado", config)["estado"]


def _esperar_container(cli: GraphClient, creation_id: str, tentativas: int = 20) -> None:
    for _ in range(tentativas):
        st = cli.get(creation_id, fields="status_code").get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise ErroPublicacao(f"container {creation_id} em {st}")
        time.sleep(3)
    raise ErroPublicacao(f"container {creation_id} não ficou pronto")


def publicar_peca(con, raiz: Path, peca_id: str, cli: GraphClient, ig_user: str, config: dict) -> dict:
    pasta = raiz / f"conteudo/{peca_id}"
    peca = yaml.safe_load((pasta / "peca.yaml").read_text(encoding="utf-8"))
    legenda = montar_legenda((pasta / "copy.md").read_text(encoding="utf-8"))
    artes = sorted(pasta.glob("arte_*.png"))
    if not artes:
        raise ErroPublicacao("sem arte_*.png")
    urls = publicar_midia(artes, raiz)
    formato = peca.get("formato")
    if formato == "story":
        cid = cli.post(f"{ig_user}/media", image_url=urls[0], media_type="STORIES")["id"]
    elif len(urls) > 1:
        filhos = [cli.post(f"{ig_user}/media", image_url=u, is_carousel_item="true")["id"] for u in urls]
        for f in filhos:
            _esperar_container(cli, f)
        cid = cli.post(f"{ig_user}/media", media_type="CAROUSEL", children=",".join(filhos), caption=legenda)["id"]
    else:
        cid = cli.post(f"{ig_user}/media", image_url=urls[0], caption=legenda)["id"]
    _esperar_container(cli, cid)
    midia = cli.post(f"{ig_user}/media_publish", creation_id=cid)["id"]
    link = ""
    try:
        link = cli.get(midia, fields="permalink").get("permalink", "")
    except ErroPublicacao:
        pass
    return {"midia_id": midia, "permalink": link}


def tick(con, raiz: Path, config: dict, cli: GraphClient | None = None, agora: str | None = None) -> list[dict]:
    """Publica agendamentos vencidos. Devolve resultados; nunca levanta exceção por peça (registra erro)."""
    log = logger("publicador", raiz)
    agora = agora or agora_iso()
    env = carregar_env(raiz)
    ig_user = env.get("AGENCIA_IG_USER_ID", "")
    vencidos = con.execute("SELECT a.id, a.peca_id, a.tentativas FROM agendamentos a JOIN pecas p ON p.id=a.peca_id WHERE a.status='AGENDADO' AND p.estado='AGENDADO' AND a.quando_utc<=? ORDER BY a.quando_utc", (agora,)).fetchall()
    saida = []
    for a in vencidos:
        peca_id = a["peca_id"]
        if not _aprovada(con, peca_id):
            con.execute("UPDATE agendamentos SET status='FALHOU', erro='sem APROVAR em aprovacoes' WHERE id=?", (a["id"],)); con.commit()
            saida.append({"peca": peca_id, "ok": False, "erro": "sem aprovação registrada"}); continue
        try:
            cli = cli or cliente_padrao(raiz)
            if not ig_user:
                raise ErroPublicacao("AGENCIA_IG_USER_ID ausente no .env (P3)")
            r = publicar_peca(con, raiz, peca_id, cli, ig_user, config)
            con.execute("UPDATE agendamentos SET status='PUBLICADO', midia_id=?, permalink=?, publicado_em=?, tentativas=tentativas+1, erro=NULL WHERE id=?",
                        (r["midia_id"], r["permalink"], agora, a["id"]))
            transicao.mover(con, raiz, peca_id, "PUBLICADO", "publicador", f"instagram {r['midia_id']} {r['permalink']}", config)
            log.info("%s publicada: %s %s", peca_id, r["midia_id"], r["permalink"])
            saida.append({"peca": peca_id, "ok": True, **r})
        except Exception as exc:  # noqa: BLE001
            tent = a["tentativas"] + 1
            status = "FALHOU" if tent >= MAX_TENTATIVAS else "AGENDADO"
            con.execute("UPDATE agendamentos SET tentativas=?, erro=?, status=? WHERE id=?", (tent, str(exc)[:500], status, a["id"])); con.commit()
            log.error("%s falhou (tentativa %d): %s", peca_id, tent, exc)
            saida.append({"peca": peca_id, "ok": False, "erro": str(exc)[:300], "tentativa": tent, "status": status})
    return saida


def medir(con, raiz: Path, config: dict, cli: GraphClient | None = None, agora: str | None = None, horas_min: int = 20) -> list[dict]:
    """Insights das peças PUBLICADAS há ≥ horas_min → metricas (fonte instagram) → MEDIDO."""
    log = logger("publicador", raiz)
    agora_dt = dt.datetime.strptime(agora or agora_iso(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    rows = con.execute("SELECT a.peca_id, a.midia_id, a.publicado_em FROM agendamentos a JOIN pecas p ON p.id=a.peca_id WHERE a.status='PUBLICADO' AND p.estado='PUBLICADO'").fetchall()
    saida = []
    for r in rows:
        pub = dt.datetime.strptime(r["publicado_em"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        if (agora_dt - pub) < dt.timedelta(hours=horas_min):
            continue
        try:
            cli = cli or cliente_padrao(raiz)
            d = cli.get(f"{r['midia_id']}/insights", metric=",".join(METRICAS_MIDIA))
            valores = {}
            for item in d.get("data", []):
                v = item.get("values", [{}])[0].get("value", item.get("total_value", {}).get("value"))
                if v is not None:
                    valores[NOME_METRICA.get(item["name"], item["name"])] = float(v)
            if not valores:
                raise ErroPublicacao("insights vazios")
            data = pub.astimezone(ZoneInfo(config.get("fuso", "America/Sao_Paulo"))).date().isoformat()
            for m, v in valores.items():
                con.execute("INSERT OR REPLACE INTO metricas (fonte, entidade_id, peca_id, data, metrica, valor, coletado_em) VALUES ('instagram',?,?,?,?,?,?)",
                            (f"midia:{r['midia_id']}", r["peca_id"], data, m, v, agora_iso()))
            con.commit()
            transicao.mover(con, raiz, r["peca_id"], "MEDIDO", "publicador", f"insights: {json.dumps(valores, ensure_ascii=False)}", config)
            log.info("%s medida: %s", r["peca_id"], valores)
            saida.append({"peca": r["peca_id"], "ok": True, "metricas": valores})
        except Exception as exc:  # noqa: BLE001
            log.error("%s medição falhou: %s", r["peca_id"], exc)
            saida.append({"peca": r["peca_id"], "ok": False, "erro": str(exc)[:300]})
    return saida


def medir_conta(con, raiz: Path, cli: GraphClient | None = None, dia: str | None = None) -> dict:
    """Seguidores e alcance do dia da conta → metricas (entidade conta:<id>)."""
    env = carregar_env(raiz)
    ig_user = env.get("AGENCIA_IG_USER_ID", "")
    cli = cli or cliente_padrao(raiz)
    dia = dia or (dt.date.today() - dt.timedelta(days=1)).isoformat()
    perfil = cli.get(ig_user, fields="followers_count,media_count,username")
    valores = {"seguidores": float(perfil.get("followers_count", 0)), "publicacoes": float(perfil.get("media_count", 0))}
    try:
        ins = cli.get(f"{ig_user}/insights", metric="reach", period="day", metric_type="total_value", since=dia, until=dia)
        for item in ins.get("data", []):
            v = item.get("total_value", {}).get("value")
            if v is not None:
                valores["alcance_conta"] = float(v)
    except ErroPublicacao as exc:
        logger("publicador", raiz).warning("alcance da conta indisponível: %s", exc)
    for m, v in valores.items():
        con.execute("INSERT OR REPLACE INTO metricas (fonte, entidade_id, data, metrica, valor, coletado_em) VALUES ('instagram',?,?,?,?,?)",
                    (f"conta:{ig_user}", dia, m, v, agora_iso()))
    con.commit()
    return {"conta": perfil.get("username"), "dia": dia, **valores}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raiz", default=str(RAIZ))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("agendar"); s.add_argument("--peca", required=True); s.add_argument("--quando", required=True)
    s = sub.add_parser("cancelar"); s.add_argument("--peca", required=True); s.add_argument("--autor", required=True)
    sub.add_parser("tick"); sub.add_parser("medir"); sub.add_parser("conta"); sub.add_parser("testar")
    a = ap.parse_args(argv)
    raiz = Path(a.raiz)
    config = carregar_config(raiz)
    con = db.inicializar(caminho_db(config, raiz))
    try:
        if a.cmd == "agendar":
            print(json.dumps(agendar(con, raiz, a.peca, a.quando, config), ensure_ascii=False))
        elif a.cmd == "cancelar":
            print(cancelar(con, raiz, a.peca, a.autor, config))
        elif a.cmd == "tick":
            print(json.dumps(tick(con, raiz, config), ensure_ascii=False, indent=1))
        elif a.cmd == "medir":
            print(json.dumps(medir(con, raiz, config), ensure_ascii=False, indent=1))
        elif a.cmd == "conta":
            print(json.dumps(medir_conta(con, raiz), ensure_ascii=False, indent=1))
        else:
            env = carregar_env(raiz)
            cli = cliente_padrao(raiz)
            print(json.dumps({"me": cli.get("me", fields="id,name"), "ig": cli.get(env.get("AGENCIA_IG_USER_ID", ""), fields="id,username,followers_count")}, ensure_ascii=False, indent=1))
        return 0
    except (ErroPublicacao, transicao.TransicaoInvalida) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
