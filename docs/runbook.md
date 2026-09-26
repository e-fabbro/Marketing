# Runbook — Agência REVERA (operação)

Raiz: `/root/.hermes/profiles/duds/agencia-revera` (= `/root/agencia-revera`). Prefixo dos scripts:
`cd /root/agencia-revera && PYTHONPATH=vendor python3 scripts/<x>.py`. Runbooks por fase: `docs/runbook-fase{2,3,4,5}.md`.

## 1. Mapa do que roda onde
| O quê | Onde | Como | Precisa de LLM |
|---|---|---|---|
| Bot de aprovação (Telegram, botões) | host, `agencia-bot-aprovacao.service` | `deploy/agencia-bot-aprovacao.service` | não |
| Serviço de render (Chromium) | host, `agencia-render.service` (127.0.0.1:8766) | `deploy/agencia-render.service` | não |
| Coleta 07:00, anomalias 09:00, tick 5 min, resumo 19:45, backup 03:00 | host, timers `agencia-*.timer` | `deploy/timers/` → `scripts/rotina.py` | não |
| Pauta seg 08:20, relatório sex 18:00, mensal dia 1 09:00, repasse à Gutcha 19:50 | container do DUDS, cron do Hermes | `deploy/cron_duds.sh --criar` | sim (DUDS + delegate_task) |
| Mídia pública para a API do Instagram | host, nginx `/agencia-midia/` → `/var/www/agencia-midia` | `deploy/nginx-agencia-midia.conf` | não |

## 2. Instalação da parte de sistema (root; só com autorização do Fabbro)
```bash
cd /root/agencia-revera
cp deploy/agencia-bot-aprovacao.service deploy/agencia-render.service deploy/timers/agencia-*.service deploy/timers/agencia-*.timer /etc/systemd/system/
systemctl daemon-reload
pkill -f bot_aprovacao.py || true; pkill -f render_servico.py || true
systemctl enable --now agencia-bot-aprovacao agencia-render agencia-manha.timer agencia-anomalias.timer agencia-tick.timer agencia-resumo.timer agencia-backup.timer
systemctl list-timers 'agencia-*' --no-pager; systemctl is-active agencia-bot-aprovacao agencia-render
# mídia pública (Fase 5)
mkdir -p /var/www/agencia-midia && chown root:www-data /var/www/agencia-midia && chmod 750 /var/www/agencia-midia
cp deploy/nginx-agencia-midia.conf /etc/nginx/snippets/agencia-midia.conf
# editar o server{} 443 de hermes.caixadeprioridades.com.br: include snippets/agencia-midia.conf;
nginx -t && systemctl reload nginx
# cron do DUDS (LLM)
bash deploy/cron_duds.sh --criar
```

## 3. Pausar tudo / retomar
```bash
# pausa total (nada publica, nada aprova, nada coleta; o DUDS continua respondendo no Telegram)
systemctl stop agencia-tick.timer agencia-manha.timer agencia-anomalias.timer agencia-resumo.timer agencia-bot-aprovacao
docker exec hermes-gateway-duds python -m hermes_cli.main --profile duds cron list      # ids dos jobs agencia-*
docker exec hermes-gateway-duds python -m hermes_cli.main --profile duds cron pause <id>   # para cada job agencia-*
# só publicação (mantém aprovação e coleta): systemctl stop agencia-tick.timer
# retomar: systemctl start ... / cron resume <id>
```
Peças AGENDADO com horário vencido publicam no primeiro `tick` após retomar; cancele antes se não quiser:
`publicar_ig.py cancelar --peca <id> --autor telegram:<seu id>`.

## 4. Reprocessar uma peça
| Situação | Comando |
|---|---|
| Estado atual | `transicao.py estado --peca <id>`; histórico em `conteudo/<id>/peca.yaml` |
| Voltar ao rascunho (de ESCALAR ou AGUARDANDO_HUMANO) | pelo bot (Ajustar), ou `transicao.py mover --peca <id> --para RASCUNHO --autor telegram:<seu id> --motivo "..."` (ESCALAR) |
| Refazer o ciclo | `pipeline.py passo --peca <id>` e delegações pelo DUDS (AGENTS.md) |
| Arte inválida 2× (pipeline parou) | corrigir o contexto (copy/tema), `rm conteudo/<id>/etapas.json` e repetir `passo` |
| Publicação FALHOU | ver `agendamentos.erro`; corrigir a causa; `UPDATE agendamentos SET status='AGENDADO', tentativas=0 WHERE peca_id='<id>'` (sqlite via python) |
| Descartar | pelo bot, ou `transicao.py mover --para DESCARTADO --autor telegram:<seu id>` |

## 5. Trocar tokens e credenciais (`.env` com chmod 600; nunca no chat/log)
| Credencial | Onde | Depois |
|---|---|---|
| Bot de aprovação | `.env` `AGENCIA_TELEGRAM_BOT_TOKEN` | `systemctl restart agencia-bot-aprovacao` |
| Instagram | `.env` `AGENCIA_IG_TOKEN`, `AGENCIA_IG_USER_ID` | `publicar_ig.py testar` |
| Google Ads (refresh token) | `docs/runbook-fase4.md` §5 (OAuth do perfil DUDS) | `metricas.py contas` |
| Render / mídia | `.env` `AGENCIA_RENDER_TOKEN`, `AGENCIA_MIDIA_*` | `systemctl restart agencia-render` |
Gravar sem exibir: `read -rsp 'valor: ' V; echo; sed -i '/^NOME=/d' .env; echo "NOME=$V" >> .env; unset V`.

## 6. Backup e restauração
Backup diário 03:00 em `dados/backups/agencia-<data>.db` (14 cópias) e, além disso, o `hermes-backup.timer` do
host copia o perfil inteiro. Restaurar: parar os timers e o bot, `cp dados/backups/agencia-<data>.db dados/agencia.db`,
`PYTHONPATH=vendor python3 scripts/db.py --init`, religar.

## 7. Logs e verificação rápida
`logs/{pipeline,especialista,bot_aprovacao,publicador,render,metricas,rotina,notificar}.log`;
`journalctl -u agencia-* --since today`; `systemctl list-timers 'agencia-*'`;
`custo.py` (tokens do mês); `relatorios/resumo_diario_<dia>.md`; `relatorios/alertas_<dia>.md`.

## 8. Limites conhecidos (26/09)
- Custo é em tokens estimados (assinatura ChatGPT, sem `usage` no `delegate_task`).
- Google Ads: token de desenvolvedor só com acesso de teste; Basic access **adiado pelo Fabbro (26/09)**. Até lá,
  coleta e alertas de Ads registram "sem dados coletados" e o relatório declara a lacuna. Quando quiser retomar:
  Centro de API da MCC 674-415-5743 (https://ads.google.com/aw/apicenter) → Basic access; nada muda no código.
- Instagram: credenciais P3 pendentes; nginx/mídia pública exige root.
- Fontes da marca desconhecidas (texto do logotipo em curvas); placeholders Georgia/Helvetica.
