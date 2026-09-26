#!/usr/bin/env bash
# Fase 2 — instala pipeline, compliance e bot. Pré-requisito: cd /root/agencia-revera && git pull --ff-only
# Idempotente. Não instala a unit systemd (isso é passo manual autorizado; ver deploy/).
set -euo pipefail
cd /root/.hermes/profiles/duds/agencia-revera
echo "== dependências em vendor/"; python3 -m pip install -q --target vendor -r requirements.txt --upgrade 2>&1 | grep -v -E 'WARNING: Running pip|dependency resolver|huggingface|^$' || true
echo "== banco (adiciona mensagens_aprovacao)"; PYTHONPATH=vendor python3 scripts/db.py --init
echo "== testes"; PYTHONPATH=vendor python3 -m pytest tests -q
echo "== .env"; chmod 600 .env
grep -qE "^AGENCIA_TELEGRAM_BOT_TOKEN=.+" .env && echo "AGENCIA_TELEGRAM_BOT_TOKEN=<definida>" || echo "AGENCIA_TELEGRAM_BOT_TOKEN=<VAZIA — preencher>"
grep -qE "^AGENCIA_LLM_BASE_URL=.+" .env && echo "AGENCIA_LLM_BASE_URL=<definida: modo direto>" || echo "AGENCIA_LLM_BASE_URL=<vazia: modo delegação (correto)>"
echo "== normas"; ls brand/normas | grep -v README || echo "(vazio: gate responde ESCALAR em item normativo)"
echo; echo "PRONTO. Próximos passos em docs/runbook-fase2.md (§2 delegação pelo DUDS, §3 bot, §4 ponta a ponta)"
