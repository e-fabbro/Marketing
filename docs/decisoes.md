# Registro de decisões de arquitetura

Formato: ID, data, status (proposta | aceita | revista), contexto, decisão, consequências.

## D1 — Mecanismo de orquestração dos especialistas
- Data: 2026-09-26 · Status: **proposta** (aguarda saída de `scripts/reconhecimento_vps.sh` e `AVANÇAR`)
- Contexto: `CLAUDE.md` §3 manda usar subagentes/skills nativos do Hermes se existirem. O `delegate_task`
  do Hermes existe, mas fixa um único modelo para todos os filhos, não tem temperatura por chamada, não
  expõe custo por chamada e não seleciona skill por chamada (`docs/reconhecimento.md` §2.2). Os critérios
  de sucesso 2 e 5 exigem log de compliance inevitável e custo por especialista.
- Decisão: especialistas são skills (`especialistas/<nome>/SKILL.md`) executadas por um script Python
  determinístico (`scripts/especialista.py`) que chama a API do provedor de LLM com modelo/temperatura por
  especialista lidos de `config/agencia.yaml`, valida a saída e grava custo e transição em `dados/agencia.db`.
  O DUDS (perfil Hermes) orquestra: dispara `scripts/pipeline.py`, lê resultados e fala com humanos.
  `delegate_task` não é o motor do pipeline.
- Consequências: pipeline testável com `pytest` sem Hermes; custo por especialista sai de graça; precisa de
  chave do provedor de LLM no `.env` da agência; o `SKILL.md` de cada especialista também fica legível pelo
  Hermes (mesmo formato de frontmatter) para uso manual do DUDS.

## D2 — Bot de aprovação no Telegram
- Data: 2026-09-26 · Status: **proposta** (decidir na Fase 2 com P1)
- Contexto: o gateway Telegram do Hermes só oferece botões inline via `clarify` e não tem API para scripts
  externos enviarem mensagens com botões (`docs/reconhecimento.md` §2.5). A seção 6 pede botões
  Aprovar/Ajustar/Descartar por peça e aprovação item a item da pauta.
- Decisão: bot de aprovação em Python (`python-telegram-bot`, PyPI) usando a Bot API diretamente, validando
  `from.id` contra `config/agencia.yaml → aprovadores` e gravando em `aprovacoes` via `transicao.py`.
  Token: preferir **bot dedicado da agência** (evita dois consumidores de `getUpdates` no bot do DUDS).
- Consequências: mais um processo (systemd) na VPS; o DUDS continua respondendo perguntas livres pelo
  gateway dele; aprovações formais só valem se vierem pelo bot da agência.

## D3 — Agendamento
- Data: 2026-09-26 · Status: **proposta**
- Decisão: rotinas da §10 no cron nativo do Hermes, no perfil do DUDS (`hermes cron create ...`,
  entrega `telegram`). Backup 03:00 do `agencia.db` em systemd timer (não precisa de LLM).
- Consequências: testar fuso horário do cron do Hermes antes de fixar 08:00/18:00.
