#!/usr/bin/env bash
# Fase 5 — Instagram. Pré-requisito: cd /root/agencia-revera && git pull --ff-only
set -euo pipefail
cd /root/.hermes/profiles/duds/agencia-revera
echo "== banco (tabela agendamentos)"; PYTHONPATH=vendor python3 scripts/db.py --init
echo "== testes"; PYTHONPATH=vendor python3 -m pytest tests -q
echo "== .env (P3)"
for v in AGENCIA_IG_TOKEN AGENCIA_IG_USER_ID AGENCIA_MIDIA_BASE_URL AGENCIA_MIDIA_DIR; do grep -qE "^$v=.+" .env && echo "$v=<definida>" || echo "$v=<VAZIA>"; done
echo "== mídia pública"; d=$(sed -nE 's/^AGENCIA_MIDIA_DIR=(.*)$/\1/p' .env); d=${d:-/var/www/agencia-midia}; [ -d "$d" ] && echo "dir ok: $d" || echo "dir ausente: $d (ver deploy/nginx-agencia-midia.conf)"
u=$(sed -nE 's#^AGENCIA_MIDIA_BASE_URL=(.*)$#\1#p' .env); [ -n "$u" ] && { echo "teste HTTP: $u/inexistente.png"; curl -s -o /dev/null -w "%{http_code}\n" "$u/inexistente.png"; }
echo "== conexão com a Graph API (sem publicar)"; PYTHONPATH=vendor python3 scripts/publicar_ig.py testar || true
echo; echo "PRONTO. Publicação de teste: docs/runbook-fase5.md §3"
