# Runbook — Fase 3: design (templates + render)

## 1. Instalar e provar os 3 formatos
```bash
cd /root/agencia-revera && git pull --ff-only && bash scripts/instalar_fase3.sh
```
Gera `conteudo/2026-09-30_teste-arte-{post,carrossel,story}/arte_*.png` (1080x1080, 1080x1350 ×3, 1080x1920).
Para olhar: `scp root@hermes.caixadeprioridades.com.br:/root/agencia-revera/conteudo/2026-09-30_teste-arte-*/arte_01.png .`

## 2. Serviço de render no host (D5) — necessário para o pipeline rodar de dentro do container do DUDS
Teste em primeiro plano:
```bash
cd /root/agencia-revera && PYTHONPATH=vendor python3 scripts/render_servico.py &
curl -s http://127.0.0.1:8766/saude; echo
curl -s -X POST http://127.0.0.1:8766/render -H 'Content-Type: application/json' -d '{"peca":"2026-09-30_teste-arte-post"}'; echo
kill %1
```
Defina no `.env`: `AGENCIA_RENDER_URL=http://127.0.0.1:8766` e um `AGENCIA_RENDER_TOKEN` qualquer (o container e o
host leem o mesmo `.env`, então o token confere dos dois lados). Como serviço (exige autorização; arquivo de sistema):
```bash
cp deploy/agencia-render.service /etc/systemd/system/ && systemctl daemon-reload
systemctl enable --now agencia-render && curl -s http://127.0.0.1:8766/saude
```

## 3. Identidade visual (P5)
- `brand/identidade-visual/paleta.yaml`: trocar os hex placeholder pelos oficiais (fonte: `Paleta de Cores cópia 2.png` do kit).
- `fontes`: famílias oficiais. Se forem fontes de arquivo, instalar no host (`/usr/local/share/fonts/`, `fc-cache -f`) e
  referenciar pelo nome; o Chromium as encontra pelo fontconfig.
- `logo`: copiar o SVG escolhido para `brand/identidade-visual/logo.svg` e apontar `logo: brand/identidade-visual/logo.svg`.
  Ex.: `cp "/root/.hermes/profiles/duds/workspace/referencias-marca-drive/VETORES RGB/SVG/<arquivo>.svg" brand/identidade-visual/logo.svg`
- Re-renderizar: `PYTHONPATH=vendor python3 scripts/render_arte.py --peca 2026-09-30_teste-arte-carrossel`.

## 4. No pipeline
`pipeline.py peca` agora chama o DESIGNER (LLM → `arte.yaml`), valida, renderiza (serviço ou local) e só então passa por
ARTE → COMPLIANCE. `arte.yaml` inválido volta uma vez ao DESIGNER com o erro; se persistir, o pipeline falha e a peça
fica em RASCUNHO. O bot de aprovação envia `arte_01.png` como prévia.
