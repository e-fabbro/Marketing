#!/usr/bin/env bash
# Fase 0 — reconhecimento SOMENTE LEITURA da VPS hermes.caixadeprioridades.com.br
# Não altera nada. Nunca imprime valores de segredos: só informa se a variável/arquivo existe.
# Uso na VPS:  bash scripts/reconhecimento_vps.sh > /tmp/reconhecimento_vps.txt
# Depois cole o conteúdo de /tmp/reconhecimento_vps.txt na conversa.

set -u
mask() { # imprime NOME=<definido|vazio> sem o valor
  local n="$1"; if [ -n "${!n:-}" ]; then echo "$n=<definido>"; else echo "$n=<vazio>"; fi
}
sec() { echo; echo "=== $1 ==="; }

sec "HOST"
hostname; date -Is; uname -srm; cat /etc/os-release 2>/dev/null | grep PRETTY_NAME
echo "user: $(whoami)"

sec "RECURSOS"
nproc; free -h | head -2; df -h / /root 2>/dev/null

sec "TOOLCHAIN"
for c in python3 pip3 node npm npx hermes systemctl sqlite3 git; do
  printf '%-10s ' "$c"; command -v "$c" >/dev/null 2>&1 && { "$c" --version 2>&1 | head -1; } || echo "AUSENTE"
done
python3 -c "import playwright,sys;print('playwright(py)',playwright.__version__)" 2>/dev/null || echo "playwright(py) AUSENTE"
python3 -c "import pytest;print('pytest',pytest.__version__)" 2>/dev/null || echo "pytest AUSENTE"
python3 -c "import yaml;print('pyyaml ok')" 2>/dev/null || echo "pyyaml AUSENTE"
python3 -c "import anthropic;print('anthropic',anthropic.__version__)" 2>/dev/null || echo "anthropic(sdk) AUSENTE"
ls -d ~/.cache/ms-playwright 2>/dev/null && ls ~/.cache/ms-playwright 2>/dev/null

sec "HERMES — versão e mecanismos"
hermes --version 2>&1 | head -3
hermes --help 2>&1 | head -60
echo "--- subcomandos relevantes"
for sub in profile cron skills gateway; do echo "## hermes $sub --help"; hermes "$sub" --help 2>&1 | head -25; done

sec "HERMES — layout de /root/.hermes"
ls -la /root/.hermes 2>&1
echo "--- profiles"; ls -la /root/.hermes/profiles 2>&1
for p in /root/.hermes/profiles/*/; do
  echo "## perfil: $p"; ls -la "$p" 2>&1
  [ -f "$p/config.yaml" ] && { echo "-- config.yaml (chaves de 1º nível):"; grep -E '^[a-zA-Z_]+:' "$p/config.yaml" | sed 's/:.*/:/' ; }
  [ -f "$p/config.yaml" ] && { echo "-- delegation/model/cron no config:"; grep -nE '^(delegation|model|provider|cron|skills|platforms|toolsets)' "$p/config.yaml"; }
  [ -d "$p/skills" ] && { echo "-- skills:"; find "$p/skills" -name SKILL.md 2>/dev/null | head -30; }
  [ -d "$p/cron" ] && { echo "-- cron:"; ls -la "$p/cron" 2>/dev/null; }
  [ -f "$p/.env" ] && { echo "-- .env (só nomes das variáveis):"; sed -nE 's/^([A-Za-z_][A-Za-z0-9_]*)=.*/\1/p' "$p/.env"; }
done

sec "HERMES — config global (chaves de 1º nível, sem valores)"
[ -f /root/.hermes/config.yaml ] && grep -E '^[a-zA-Z_]+:' /root/.hermes/config.yaml | sed 's/:.*/:/'
[ -f /root/.hermes/.env ] && { echo "-- .env global (só nomes):"; sed -nE 's/^([A-Za-z_][A-Za-z0-9_]*)=.*/\1/p' /root/.hermes/.env; }
echo "-- skills globais:"; find /root/.hermes/skills -name SKILL.md 2>/dev/null | head -40
echo "-- exemplo de frontmatter de uma SKILL.md:"; f=$(find /root/.hermes/skills -name SKILL.md 2>/dev/null | head -1); [ -n "$f" ] && sed -n '1,15p' "$f"
echo "-- cron global:"; ls -la /root/.hermes/cron 2>/dev/null; hermes cron list 2>&1 | head -30

sec "DUDS — localizar perfil e credenciais (sem valores)"
find / -maxdepth 5 -iname '*duds*' -not -path '*/proc/*' 2>/dev/null | head -30
mask DUDS_GOOGLE_ADS_REFRESH_TOKEN
mask TELEGRAM_HOME_CHANNEL
grep -rlsE 'DUDS_GOOGLE_ADS_REFRESH_TOKEN|GOOGLE_ADS' /root/.hermes --include='.env' --include='*.yaml' 2>/dev/null | head
echo "-- JSON OAuth Google (Desktop app): caminhos candidatos"
find /root -maxdepth 4 -name '*.json' 2>/dev/null | xargs -r grep -ls '"installed"' 2>/dev/null | head

sec "PROCESSOS E TIMERS"
ps -eo pid,etime,cmd | grep -iE 'hermes|gateway|telegram' | grep -v grep
systemctl list-units --type=service --no-pager 2>/dev/null | grep -iE 'hermes|gutcha|nexo|roberta|cida|judite|duds'
systemctl list-timers --no-pager 2>/dev/null | head -20

sec "PORTAS EM ESCUTA"
ss -tlnp 2>/dev/null | head -20

sec "FIM"
