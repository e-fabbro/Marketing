#!/usr/bin/env bash
# Fase 6 — rotinas, custos e runbook. Pré-requisito: cd /root/agencia-revera && git pull --ff-only
# Parte 1 (sem root além do próprio repo): testes, custo, resumo de teste. Parte 2 (arquivos de sistema, só com
# autorização do Fabbro): units/timers em /etc/systemd/system, nginx, /var/www/agencia-midia — ver docs/runbook.md §2.
set -euo pipefail
cd /root/.hermes/profiles/duds/agencia-revera
echo "== testes"; PYTHONPATH=vendor python3 -m pytest tests -q
echo "== custo do mês"; PYTHONPATH=vendor python3 scripts/custo.py || true
echo "== resumo diário (sem enviar)"; PYTHONPATH=vendor python3 scripts/rotina.py resumo --sem-notificar && tail -12 relatorios/resumo_diario_*.md | tail -12
echo "== backup"; PYTHONPATH=vendor python3 scripts/rotina.py backup --sem-notificar && ls -la dados/backups/
echo "== jobs de cron do DUDS (só lista)"; bash deploy/cron_duds.sh
echo; echo "PRONTO (parte 1). Parte 2 exige autorização: docs/runbook.md §2."
