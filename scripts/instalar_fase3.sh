#!/usr/bin/env bash
# Fase 3 — render de artes no host. Pré-requisito: cd /root/agencia-revera && git pull --ff-only
set -euo pipefail
cd /root/.hermes/profiles/duds/agencia-revera
echo "== dependências em vendor/"; python3 -m pip install -q --target vendor -r requirements.txt --upgrade 2>&1 | grep -v -E 'WARNING: Running pip|dependency resolver|hermes-agent|huggingface|^$' || true
echo "== chromium"; PYTHONPATH=vendor python3 -c "import sys; sys.path.insert(0,'scripts'); import render_arte as r; c=r.encontrar_chromium(); r.verificar_viewport(c); print('ok:', c)"
echo "== testes"; PYTHONPATH=vendor python3 -m pytest tests -q
echo "== peça de teste nos 3 formatos"
for t in post:1080x1080 carrossel:1080x1350 story:1080x1920; do
  tpl=${t%%:*}; fmt=${t##*:}; id="2026-09-30_teste-arte-$tpl"; mkdir -p "conteudo/$id"
  n=1; [ "$tpl" = carrossel ] && n=3
  { echo "peca: \"$id\""; echo "template: $tpl"; echo "formatos: [$fmt]"; echo "slides:";
    for i in $(seq 1 $n); do echo "  - titulo: \"Slide $i de teste\""; echo "    corpo: \"Texto curto de teste para conferir o template $tpl no formato $fmt.\""; echo "    destaque: \"teste\""; done
    echo "assinatura: \"Dra. Jessica Jacomelli — CRM-DF 27043 — RQE 22349\""; echo "alt_text: \"Arte de teste $tpl.\""; } > "conteudo/$id/arte.yaml"
  PYTHONPATH=vendor python3 scripts/render_arte.py --peca "$id"
done
ls -la conteudo/2026-09-30_teste-arte-*/arte_*.png
echo; echo "== .env"; grep -qE '^AGENCIA_RENDER_URL=.+' .env && echo "AGENCIA_RENDER_URL=<definida>" || echo "AGENCIA_RENDER_URL=<vazia — dentro do container o pipeline precisa dela>"
echo; echo "PRONTO. Veja as PNGs (ex.: scp) e siga docs/runbook-fase3.md para o serviço de render."
