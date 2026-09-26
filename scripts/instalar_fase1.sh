#!/usr/bin/env bash
# Fase 1 — instala o esqueleto na VPS. Idempotente. Só toca em agencia-revera/ e no AGENTS.md do DUDS.
# Uso (na VPS): bash /root/agencia-revera/scripts/instalar_fase1.sh
set -euo pipefail
RAIZ=/root/.hermes/profiles/duds/agencia-revera
PERFIL=/root/.hermes/profiles/duds
cd "$RAIZ"

echo "== git pull"; git pull --ff-only

echo "== pastas"; mkdir -p conteudo dados relatorios logs brand/normas brand/identidade-visual templates/arte

echo "== dependências em vendor/ (pip --target; imagem do DUDS não aceita pip persistente)"
python3 -m pip install -q --target vendor -r requirements.txt --upgrade

echo "== .env"; if [ ! -f .env ]; then cp .env.example .env; fi; chmod 600 .env

echo "== banco"; PYTHONPATH=vendor python3 scripts/db.py --init

echo "== testes"; PYTHONPATH=vendor python3 -m pytest tests -q

echo "== AGENTS.md do DUDS"
ALVO="$PERFIL/AGENTS.md"; FONTE="$RAIZ/duds/AGENTS.md"
if [ -L "$ALVO" ] && [ "$(readlink -f "$ALVO")" = "$FONTE" ]; then
  echo "já instalado (symlink)"
elif [ -e "$ALVO" ]; then
  echo "AVISO: $ALVO já existe e não é o nosso symlink. Não sobrescrevo. Compare com $FONTE e decida."
else
  ln -s "$FONTE" "$ALVO"; echo "symlink criado: $ALVO -> $FONTE"
fi

echo "== permissões"; chmod 600 .env; ls -la .env dados/agencia.db "$ALVO"
echo
echo "PRONTO. Teste manual: no Telegram do DUDS, abra sessão nova (/new) e pergunte: qual é o seu papel?"
echo "O AGENTS.md é lido no início da sessão; não é preciso reiniciar o gateway."
