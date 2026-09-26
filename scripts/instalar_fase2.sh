#!/usr/bin/env bash
# Fase 2 — instala pipeline, compliance e bot. Pré-requisito: cd /root/agencia-revera && git pull --ff-only
# Idempotente. Não instala a unit systemd (isso é passo manual autorizado; ver deploy/).
set -euo pipefail
cd /root/.hermes/profiles/duds/agencia-revera
echo "== dependências em vendor/"; python3 -m pip install -q --target vendor -r requirements.txt --upgrade 2>&1 | grep -v -E 'WARNING: Running pip|dependency resolver|huggingface|^$' || true
echo "== banco (adiciona mensagens_aprovacao)"; PYTHONPATH=vendor python3 scripts/db.py --init
echo "== testes"; PYTHONPATH=vendor python3 -m pytest tests -q
echo "== .env"; chmod 600 .env
for v in AGENCIA_TELEGRAM_BOT_TOKEN AGENCIA_LLM_BASE_URL; do grep -qE "^$v=.+" .env && echo "$v=<definida>" || echo "$v=<VAZIA — preencher>"; done
echo "== normas"; ls brand/normas | grep -v README || echo "(vazio: gate responde ESCALAR em item normativo)"
echo; echo "PRONTO. Próximos passos: bash scripts/testar_llm.sh ; depois o teste ponta a ponta em docs/runbook-fase2.md"
