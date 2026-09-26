#!/usr/bin/env bash
# Fase 4 — tráfego e análise. Pré-requisito: cd /root/agencia-revera && git pull --ff-only
set -euo pipefail
cd /root/.hermes/profiles/duds/agencia-revera
echo "== testes"; PYTHONPATH=vendor python3 -m pytest tests -q
echo "== venv do MCP google-ads"
PYTHONPATH=vendor python3 -c "
import sys; sys.path.insert(0,'scripts'); import metricas, subprocess
from pathlib import Path
cmd = metricas.ads_comando(Path('.'))
print('comando:', ' '.join(cmd))
r = subprocess.run(cmd + ['-c', 'import google.ads.googleads, google.oauth2.credentials; print(\"google-ads ok\")'], capture_output=True, text=True, timeout=120)
print(r.stdout.strip() or r.stderr.strip()[-400:])
r.returncode == 0 or sys.exit(1)"
echo "== contas acessíveis (API real, somente leitura)"; PYTHONPATH=vendor python3 scripts/metricas.py contas
echo "== coleta dos últimos 14 dias"; PYTHONPATH=vendor python3 scripts/metricas.py coletar --dias 14
echo "== extrato da última semana completa"
SEG=$(date -d "last monday -7 days" +%F); DOM=$(date -d "$SEG +6 days" +%F)
PYTHONPATH=vendor python3 scripts/metricas.py extrato --de "$SEG" --ate "$DOM" --md
echo; echo "== anomalias de ontem"; PYTHONPATH=vendor python3 scripts/metricas.py anomalias
echo; echo "PRONTO. Relatório semanal: docs/runbook-fase4.md §3 (delegação pelo DUDS). Semana sugerida: $SEG"
