# Runbook — Fase 5: Instagram (Insights + publicação agendada)

## 1. Pré-requisitos (P3)
1. Conta Instagram **Profissional** vinculada a uma **Página do Facebook**.
2. No app Meta existente (o do WhatsApp da Gutcha): produto "Instagram Graph API" adicionado; permissões
   `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`, `pages_read_engagement`.
   Para uso em produção sem revisão do app, a conta precisa ter papel no app (usuário de sistema do Business
   Manager com a Página e a conta IG atribuídas) e o token ser de usuário de sistema ou de longa duração.
3. `AGENCIA_IG_USER_ID`: ID da conta IG (Graph: `GET /me/accounts` → página → `?fields=instagram_business_account`).
4. Mídia pública: `deploy/nginx-agencia-midia.conf` (exige root) — a API do Instagram só aceita imagem por URL.

## 2. Instalar e testar a conexão
```bash
cd /root/agencia-revera && git pull --ff-only && bash scripts/instalar_fase5.sh
```
`publicar_ig.py testar` faz `GET /me` e `GET /{ig_user}`; nada é publicado.

## 3. Publicação de teste (critério de pronto)
Use uma peça APROVADA pelo bot (ex.: `2026-10-01_teste-delegacao`, já aprovada em 26/09) ou aprove outra.
```bash
cd /root/agencia-revera && export PYTHONPATH=vendor
python3 scripts/publicar_ig.py agendar --peca 2026-10-01_teste-delegacao --quando "2026-09-27 09:30"   # hora local
python3 scripts/publicar_ig.py tick          # antes da hora: []; depois: publica, imprime midia_id e permalink
python3 scripts/transicao.py estado --peca 2026-10-01_teste-delegacao     # PUBLICADO
```
No dia seguinte (≥ 20 h depois):
```bash
python3 scripts/publicar_ig.py medir         # insights → metricas → MEDIDO
python3 scripts/publicar_ig.py conta         # seguidores/alcance da conta
python3 scripts/metricas.py extrato --de 2026-09-27 --ate 2026-09-27 --md
```
Na Fase 6, `tick` roda a cada 5 min e `medir`/`conta` às 07:00 junto com a coleta do Ads.
Cancelar antes da hora: `python3 scripts/publicar_ig.py cancelar --peca <id> --autor telegram:<seu id>`.

## 4. Falhas
- `Graph 190`: token inválido/expirado → gerar novo token (P3) e atualizar `.env`.
- `Graph 100 ... image_url`: a URL pública não respondeu 200 com `image/png` → conferir nginx e `AGENCIA_MIDIA_BASE_URL`.
- 3 falhas → `agendamentos.status = FALHOU`, peça fica em AGENDADO; corrigir e reagendar (cancelar + novo ciclo) ou
  `UPDATE agendamentos SET status='AGENDADO', tentativas=0` só após a causa resolvida.
