#!/usr/bin/env bash
# Rotinas com LLM: cron nativo do Hermes no perfil do DUDS (rodam dentro do container do gateway).
# O cron do Hermes grava horários em UTC (confirmado): 08:20 BRT = 11:20 UTC etc. Entrega no grupo "Marketing - Duds".
# Idempotência: o Hermes cria job novo a cada `create`; rode `list` antes e `remove <id>` para trocar.
set -euo pipefail
H="docker exec hermes-gateway-duds python -m hermes_cli.main --profile duds"
R=/root/.hermes/profiles/duds/agencia-revera
GRUPO="telegram:-5238127555"

echo "== jobs atuais"; $H cron list
if [ "${1:-}" != "--criar" ]; then echo "Rode com --criar para cadastrar os 4 jobs abaixo."; exit 0; fi

# Segunda 08:20 BRT — pauta semanal (20 min depois da pesquisa diária das 08:00, que alimenta o ESTRATEGISTA)
$H cron create "20 11 * * 1" "Agência REVERA — pauta semanal. Leia $R/duds/AGENTS.md (seção 'Como você aciona os especialistas'). Semana alvo: a próxima segunda-feira (AAAA-MM-DD). Rode 'cd $R && PYTHONPATH=vendor python3 scripts/pipeline.py pauta --semana <data>', delegue o prompt ao ESTRATEGISTA, entregue com 'pipeline.py entregar --pauta <data> --arquivo <resposta> --criar'. Depois, para cada peça criada, rode o ciclo 'pipeline.py passo/entregar' até o fim. Ao terminar, envie ao grupo uma mensagem única listando as peças da semana (id, tema, formato, estado) e diga que a aprovação é item a item pelo bot da agência." --name agencia-pauta-semanal --deliver "$GRUPO"

# Sexta 18:00 BRT — relatório semanal
$H cron create "0 21 * * 5" "Agência REVERA — relatório semanal. Leia $R/duds/AGENTS.md (seção 'Métricas, alertas e relatórios'). Semana: a segunda-feira desta semana (AAAA-MM-DD). Rode 'cd $R && PYTHONPATH=vendor python3 scripts/relatorio.py preparar --tipo semanal --semana <data>', delegue ao ANALISTA, entregue com 'relatorio.py entregar --id semanal_<data> --arquivo <resposta>'. Se a entrega recusar por números sem origem, delegue de novo com o erro. Envie ao grupo o conteúdo de relatorios/semanal_<data>.md." --name agencia-relatorio-semanal --deliver "$GRUPO"

# Dia 1, 09:00 BRT — relatório mensal + proposta de calendário
$H cron create "0 12 1 * *" "Agência REVERA — relatório mensal e calendário. Mês anterior (AAAA-MM). Rode 'cd $R && PYTHONPATH=vendor python3 scripts/relatorio.py preparar --tipo mensal --mes <mes>', delegue ao ANALISTA, entregue com 'relatorio.py entregar --id mensal_<mes> --arquivo <resposta>'. Depois rode 'PYTHONPATH=vendor python3 scripts/custo.py --mes <mes>' e inclua a tabela. Por fim, delegue ao ESTRATEGISTA (via 'pipeline.py pauta --semana <primeira segunda do mês>') apenas a proposta de calendário do mês, sem --criar. Envie ao grupo o relatório e a proposta; nada é criado sem aprovação." --name agencia-relatorio-mensal --deliver "$GRUPO"

# Diário 19:50 BRT — repasse do resumo à Gutcha (o resumo em si é determinístico, gerado 19:45 pelo timer)
$H cron create "50 22 * * *" "Agência REVERA — repasse à Gutcha. Leia $R/relatorios/resumo_diario_<hoje AAAA-MM-DD>.md. Envie o conteúdo, sem alterar números, à Gutcha pelo canal que você usa para falar com ela (kanban ou mensagem), para o fechamento das 20h. Se o arquivo não existir, avise o grupo que a rotina das 19:45 falhou." --name agencia-resumo-gutcha --deliver "$GRUPO"

echo; echo "== depois"; $H cron list
