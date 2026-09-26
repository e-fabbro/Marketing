#!/usr/bin/env bash
# Fase 1 — leitura SOMENTE do perfil do DUDS para integrar sem duplicar. Mascara valores de segredo.
# Uso (na VPS): bash /root/agencia-revera/scripts/ler_contexto_duds.sh > /tmp/contexto_duds.txt
set -u
P=/root/.hermes/profiles/duds
mascarar() { sed -E 's/((token|key|secret|password|senha|api_key|client_id|client_secret|refresh)[a-z_]*[[:space:]]*[:=][[:space:]]*)["'"'"']?[^"'"'"' ]+/\1<mascarado>/Ig'; }
sec() { echo; echo "=== $1 ==="; }

sec "SOUL.md"; cat "$P/SOUL.md"
sec "profile.yaml"; cat "$P/profile.yaml" 2>/dev/null
sec "config.yaml (valores sensíveis mascarados)"; mascarar < "$P/config.yaml"
sec "cron/jobs.json (mascarado)"; mascarar < "$P/cron/jobs.json" 2>/dev/null
sec "skills — frontmatter de cada uma"
for f in $(find "$P/skills" -name SKILL.md | sort); do echo "--- $f"; awk 'NR==1,/^---$/ && NR>1 {print} NR>1 && /^---$/ {exit}' "$f" | head -12; done
sec "skill duds-orquestrador (inteira)"; cat "$P/skills/duds/duds-orquestrador/SKILL.md"
sec "skill conformidade-cfm (inteira)"; cat "$P/skills/duds/conformidade-cfm/SKILL.md"
sec "memories (nomes e tamanho)"; ls -la "$P/memories" 2>/dev/null
sec "workspace (1 nível)"; ls -la "$P/workspace" 2>/dev/null
sec "ARQUITETURA-DUDS.md"; cat /home/gutcha-codex/ccb-reel-studio-windows/ARQUITETURA-DUDS.md 2>/dev/null | head -200
sec "FIM"
