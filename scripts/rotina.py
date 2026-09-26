#!/usr/bin/env python3
"""Rotinas determinísticas (chamadas pelos timers systemd no host):
  rotina.py manha        07:00  coleta Ads + conta/medição Instagram + backup do dia anterior conferido
  rotina.py anomalias    09:00  alertas do Ads → relatorios/alertas_<dia>.md → grupo (se houver)
  rotina.py tick         5 min  publica agendamentos vencidos (publicar_ig.tick); falhas → grupo
  rotina.py resumo       19:45  resumo diário → relatorios/resumo_diario_<dia>.md → grupo (a Gutcha recebe pelo cron do DUDS)
  rotina.py backup       03:00  cópia consistente do agencia.db em dados/backups/ (mantém 14)
Toda rotina registra em logs/rotina.log e nunca chama modelo.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import custo  # noqa: E402
import db  # noqa: E402
import metricas  # noqa: E402
import notificar  # noqa: E402
import publicar_ig  # noqa: E402
from comum import RAIZ, agora_iso, caminho_db, carregar_config, carregar_env, logger  # noqa: E402


def backup(raiz: Path, con, manter: int = 14) -> Path:
    pasta = raiz / "dados" / "backups"; pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"agencia-{dt.date.today().isoformat()}.db"
    alvo = db.conectar(destino)
    con.backup(alvo)          # cópia consistente mesmo com WAL
    alvo.close()
    antigos = sorted(pasta.glob("agencia-*.db"))[:-manter]
    for a in antigos:
        a.unlink()
    return destino


def resumo_diario(raiz: Path, con, config: dict, dia: str | None = None) -> str:
    tz = ZoneInfo(config.get("fuso", "America/Sao_Paulo"))
    dia = dia or dt.datetime.now(tz).date().isoformat()
    ini, fim = f"{dia}T00:00:00Z", f"{dia}T23:59:59Z"
    estados = {r["estado"]: r["n"] for r in con.execute("SELECT estado, COUNT(*) n FROM pecas GROUP BY estado")}
    trans = con.execute("SELECT peca_id, de, para, autor FROM transicoes WHERE timestamp BETWEEN ? AND ? ORDER BY id", (ini, fim)).fetchall()
    aprov = con.execute("SELECT peca_id, decisao, telegram_nome FROM aprovacoes WHERE timestamp BETWEEN ? AND ?", (ini, fim)).fetchall()
    pub = con.execute("SELECT peca_id, permalink FROM agendamentos WHERE status='PUBLICADO' AND publicado_em BETWEEN ? AND ?", (ini, fim)).fetchall()
    falhas = con.execute("SELECT peca_id, erro FROM agendamentos WHERE status='FALHOU'").fetchall()
    pend = [r["id"] for r in con.execute("SELECT id FROM pecas WHERE estado IN ('AGUARDANDO_HUMANO','ESCALAR')")]
    alertas = (raiz / "relatorios" / f"alertas_{(dt.date.fromisoformat(dia) - dt.timedelta(days=1)).isoformat()}.md")
    c = custo.resumo(con, config, dia[:7])
    linhas = [f"📋 Agência REVERA — resumo de {dia}",
              f"Peças por estado: " + (", ".join(f"{k} {v}" for k, v in sorted(estados.items())) or "nenhuma"),
              f"Transições hoje: {len(trans)} · decisões humanas: " + (", ".join(f"{a['decisao']} {a['peca_id']} ({a['telegram_nome'] or '?'})" for a in aprov) or "nenhuma"),
              f"Publicadas hoje: " + (", ".join(f"{p['peca_id']} {p['permalink'] or ''}".strip() for p in pub) or "nenhuma"),
              f"Aguardando decisão humana: " + (", ".join(pend) or "nada"),
              f"Falhas de publicação abertas: " + (", ".join(f"{f['peca_id']} ({(f['erro'] or '')[:60]})" for f in falhas) or "nenhuma"),
              f"Alertas de Ads (ontem): " + (alertas.read_text(encoding='utf-8').splitlines()[0] if alertas.exists() else "sem arquivo"),
              f"Tokens no mês: {c['total_tokens']}" + (" ⚠️ teto estourado" if c["estourados"] else ""),
              "Dinheiro: nenhum gasto novo foi autorizado pela agência (toda mudança de verba exige aprovação)."]
    texto = "\n".join(linhas)
    (raiz / "relatorios").mkdir(exist_ok=True)
    (raiz / "relatorios" / f"resumo_diario_{dia}.md").write_text(texto + "\n", encoding="utf-8")
    return texto


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["manha", "anomalias", "tick", "resumo", "backup"])
    ap.add_argument("--raiz", default=str(RAIZ))
    ap.add_argument("--sem-notificar", action="store_true")
    a = ap.parse_args(argv)
    raiz = Path(a.raiz); config = carregar_config(raiz); log = logger("rotina", raiz)
    con = db.inicializar(caminho_db(config, raiz))
    env = carregar_env(raiz)
    notif = (lambda t: True) if a.sem_notificar else (lambda t: notificar.enviar(t, raiz))
    try:
        if a.cmd == "manha":
            r = metricas.coletar(raiz=raiz, con=con, config=config, dias=3)
            log.info("coleta ads: %s", json.dumps(r, ensure_ascii=False))
            if env.get("AGENCIA_IG_TOKEN"):
                log.info("ig conta: %s", publicar_ig.medir_conta(con, raiz))
                log.info("ig medir: %s", publicar_ig.medir(con, raiz, config))
            erros = {k: v["erro"] for k, v in r.get("contas", {}).items() if "erro" in v}
            if r.get("erro") or erros:
                notif(f"⚠️ Coleta de métricas com erro: {r.get('erro') or erros}")
        elif a.cmd == "anomalias":
            dia = (dt.date.today() - dt.timedelta(days=1)).isoformat()
            al = metricas.anomalias(con, raiz, dia)
            texto = metricas.alertas_md(al, dia)
            (raiz / "relatorios" / f"alertas_{dia}.md").write_text(texto + "\n", encoding="utf-8")
            log.info("anomalias: %d", len(al))
            if al:
                notif(texto)
        elif a.cmd == "tick":
            res = publicar_ig.tick(con, raiz, config)
            for x in res:
                log.info("tick: %s", json.dumps(x, ensure_ascii=False))
                if x.get("ok"):
                    notif(f"✅ Publicada: {x['peca']} {x.get('permalink', '')}".strip())
                elif x.get("status") == "FALHOU":
                    notif(f"❌ Publicação FALHOU após 3 tentativas: {x['peca']} — {x.get('erro')}")
        elif a.cmd == "resumo":
            texto = resumo_diario(raiz, con, config)
            notif(texto)
        else:
            p = backup(raiz, con)
            log.info("backup: %s (%d bytes)", p, p.stat().st_size)
        return 0
    except Exception as exc:  # noqa: BLE001
        log.exception("rotina %s falhou: %s", a.cmd, exc)
        notif(f"❌ Rotina {a.cmd} falhou: {str(exc)[:300]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
