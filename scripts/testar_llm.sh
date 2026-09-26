#!/usr/bin/env bash
# Fase 2 — descobre e testa o endpoint OpenAI-compatível dos especialistas (D1b: hermes proxy do DUDS).
# Somente leitura. Nunca imprime token. Uso (na VPS): bash /root/agencia-revera/scripts/testar_llm.sh
set -u
cd /root/.hermes/profiles/duds/agencia-revera
echo "=== 1. O que o hermes 0.19 do container sabe sobre 'proxy'"
docker exec hermes-gateway-duds python -m hermes_cli.main --profile duds proxy --help 2>&1 | head -40
echo; echo "=== 2. Portas em escuta agora (procurar a do proxy, se já estiver ativo)"
ss -tlnp 2>/dev/null | grep -E '127.0.0.1:(8788|8080|4000|11434|1234)' || echo "(nenhuma das portas típicas)"
echo; echo "=== 3. Endpoint configurado no .env"
BASE=$(sed -nE 's/^AGENCIA_LLM_BASE_URL=(.*)$/\1/p' .env); KEY=$(sed -nE 's/^AGENCIA_LLM_API_KEY=(.*)$/\1/p' .env)
echo "AGENCIA_LLM_BASE_URL=${BASE:-<vazio>}"; [ -n "$KEY" ] && echo "AGENCIA_LLM_API_KEY=<definida>" || echo "AGENCIA_LLM_API_KEY=<vazia>"
[ -z "$BASE" ] && { echo "defina AGENCIA_LLM_BASE_URL no .env e rode de novo"; exit 1; }
echo; echo "=== 4. GET /models"
curl -sS -m 15 -H "Authorization: Bearer ${KEY}" "$BASE/models" | head -c 1500; echo
echo; echo "=== 5. Chat mínimo com gpt-5.6-terra (deve responder 'ok')"
curl -sS -m 60 -H "Authorization: Bearer ${KEY}" -H 'Content-Type: application/json' "$BASE/chat/completions" \
  -d '{"model":"gpt-5.6-terra","max_tokens":5,"messages":[{"role":"user","content":"responda só: ok"}]}' | head -c 800; echo
