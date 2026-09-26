# AGÊNCIA REVERA — Marketing da Dra. Jessica, orquestrada pelo DUDS

> Fonte de verdade do projeto. Claude Code: leia este arquivo inteiro antes de qualquer ação.
> Execute UMA fase por vez. Ao fim de cada fase: pare, informe "Fase N de 6 concluída: X. Próxima: Y",
> mostre os comandos de teste do que passou a funcionar e aguarde o comando `AVANÇAR`.

---

## 1. Objetivo

Agência de marketing autônoma, rodando na VPS `hermes.caixadeprioridades.com.br`, para o consultório da
Dra. Jessica (psiquiatria — Instituto REVERA de Psiquiatria Intervencionista e Saúde Mental da Mulher).
Os agentes planejam, produzem, revisam, publicam, gerem tráfego pago e reportam. Humanos só aprovam.

### Critérios de sucesso (verificáveis)
1. Pauta semanal gerada toda segunda às 08:00 e enviada para aprovação.
2. 100% das peças passam pelo gate de compliance antes de chegar à aprovação humana (log comprova).
3. Zero publicação, resposta pública ou alteração de verba/campanha sem aprovação registrada no banco.
4. Relatório semanal toda sexta às 18:00 só com números vindos das APIs — nenhum número estimado.
5. Custo mensal de API registrado por especialista e abaixo do teto definido em `config/agencia.yaml`.

---

## 2. Ambiente conhecido (CONFIRMAR na Fase 0 — não presumir)

- Hermes em `/root/.hermes`; perfis em `/root/.hermes/profiles/<nome>/` com `AGENTS.md`, `config.yaml`, `plugins/`, `state/`.
- Perfis/agentes existentes: Gutcha (orquestradora geral, fechamento diário às 20h), Nexo (delegacia), Roberta (consultório), Cida, Judite.
- DUDS já existe: credencial OAuth Google tipo "Desktop app" (JSON salvo no host) e refresh token do Google Ads na variável `DUDS_GOOGLE_ADS_REFRESH_TOKEN`. Localizar onde o perfil do DUDS está.
- Escalonamentos do ecossistema vão para `TELEGRAM_HOME_CHANNEL`.
- App Meta for Developers já existe (usado no WhatsApp da Gutcha).
- Escopo de escrita permitido sem perguntar: `/root/agencia-revera/` e o perfil do DUDS. Qualquer outro perfil ou arquivo do sistema: pedir antes.

---

## 3. Arquitetura

```
                 Dra. Jessica / Fabbro  (aprovação via Telegram)
                              │
                           [ DUDS ]  ← orquestrador: único que fala com humanos
        ┌──────────┬─────────┼──────────┬───────────┬───────────┐
  ESTRATEGISTA  REDATOR  DESIGNER  COMPLIANCE  TRÁFEGO   ANALISTA   (+ PUBLICADOR = script)
                              │
              Gutcha (resumo diário + escalonamento de dinheiro)
              Roberta (recebe leads de agendamento)
```

Regras de orquestração:
- Especialistas não falam com humanos nem entre si. O DUDS encadeia as chamadas e guarda o estado.
- Cada especialista recebe só o contexto de que precisa (peça + arquivos da marca pertinentes).
- Mecanismo: usar o recurso nativo de subagentes/delegação/skills da versão do Hermes instalada. Se não existir, cada especialista vira uma skill (`especialistas/<nome>/SKILL.md` + scripts) invocada em sequência pelo DUDS. Registrar a escolha em `docs/decisoes.md`.

### Especialistas

| Especialista | Função | Saída | Modelo sugerido | Ação externa? |
|---|---|---|---|---|
| ESTRATEGISTA | posicionamento, personas, pilares, calendário mensal, pauta semanal | `pauta.yaml` | Opus ou Sonnet | não |
| REDATOR | legendas, roteiros de reels, carrosséis, stories, anúncios, posts Google Business, artigos | `copy.md` | Sonnet | não |
| DESIGNER | artes a partir de templates HTML/CSS da marca renderizados em PNG (Playwright): 1080x1350, 1080x1920, 1080x1080 | `arte*.png` | Sonnet | não |
| COMPLIANCE | gate obrigatório com poder de veto (seção 5) | `compliance.json` | Sonnet, temperatura baixa | não |
| TRÁFEGO | Google Ads via API: leitura, diagnóstico, propostas de ajuste; Meta Ads em fase futura | `proposta_ads.md` | Sonnet | só com aprovação |
| ANALISTA | coleta de métricas, SQLite, relatórios semanal/mensal, alertas de anomalia | `relatorios/*.md` | Haiku (coleta) + Sonnet (análise) | não |
| PUBLICADOR | script determinístico, sem LLM: agenda e publica peças APROVADAS | log | — | só com aprovação |

Cada `SKILL.md` de especialista deve ter: papel, entradas, formato exato de saída, 2 exemplos bons, 2 anti-exemplos, critério de pronto.

---

## 4. Pipeline de conteúdo (máquina de estados)

```
PAUTA → RASCUNHO → ARTE → COMPLIANCE ─┬─ APROVADO_COMPLIANCE → AGUARDANDO_HUMANO ─┬─ APROVADO → AGENDADO → PUBLICADO → MEDIDO
                                      ├─ REPROVADO → RASCUNHO (máx. 2 voltas; na 3ª, escala ao humano)
                                      └─ ESCALAR (dúvida normativa → humano decide)
                                                                                  ├─ AJUSTAR → RASCUNHO
                                                                                  └─ DESCARTADO
```

- Cada peça: pasta `conteudo/AAAA-MM-DD_slug/` com `peca.yaml` (id, estado, canal, formato, pilar, objetivo, CTA, histórico de transições com autor e timestamp), `copy.md`, `arte*.png`, `compliance.json`.
- Toda transição passa por `scripts/transicao.py`, que valida a transição permitida e grava em `dados/agencia.db`. Transição inválida = erro, nunca silêncio.
- APROVADO só é aceito vindo de IDs de Telegram listados em `config/agencia.yaml` → `aprovadores`.

---

## 5. Gate de compliance médico

Fontes normativas ficam em `brand/normas/` (textos oficiais baixados pelo Fabbro). O agente decide com base nesses textos, não de memória. Em dúvida: ESCALAR, nunca aprovar.

Checklist mínimo (cada item em `compliance.json` com `ok | falha | n/a` + justificativa):
1. Identificação da médica com nome, CRM/UF e RQE em peça que mencione especialidade (Res. CFM 2.336/2023 — conferir texto vigente).
2. Nenhuma promessa ou garantia de resultado; nenhum sensacionalismo ou superioridade não comprovada.
3. Nenhum diagnóstico, prescrição ou conduta individual em post, comentário ou DM.
4. Nenhum dado, imagem ou relato identificável de paciente. Depoimentos e antes/depois: bloqueados por padrão; só com decisão humana explícita e checagem do texto normativo.
5. Preços, descontos, sorteios e brindes: conferir regra vigente em `brand/normas/`; sem regra clara → ESCALAR.
6. Saúde mental: comunicação responsável — tema suicídio/autolesão sem detalhes de método e com CVV 188; sem estigmatizar transtornos.
7. Políticas de anúncios de saúde do Google e da Meta (segmentação e texto) para peças pagas.
8. Aderência a `brand/tom-de-voz.md` e `brand/proibidos.md`.

Teste automatizado obrigatório: uma peça com "cura garantida em 30 dias" e outra sem CRM/RQE devem ser REPROVADAS. O compliance nunca é pulado, inclusive em pedidos marcados como urgentes.

---

## 6. Aprovação humana

- Canal: bot de Telegram do DUDS em grupo com Jessica e Fabbro (confirmar — PENDÊNCIA P1).
- Mensagem por peça: prévia da arte + legenda + resumo do parecer de compliance + botões `Aprovar` / `Ajustar` (texto livre) / `Descartar`.
- Pauta semanal: uma única mensagem com todas as peças da semana, aprovação item a item.
- Exigem aprovação: publicar, responder publicamente, qualquer mudança em campanha, verba, lance ou público, qualquer gasto novo.
- Livres: leitura de APIs, rascunhos, análises, relatórios.
- Dinheiro: todo gasto novo escala imediatamente ao Fabbro, sem teto de alçada.

---

## 7. Base de conhecimento da marca (`brand/`)

| Arquivo | Conteúdo |
|---|---|
| `marca.md` | nomes (REVERA — sem acento), posicionamento, diferenciais, público, cidade, CRM/RQE |
| `tom-de-voz.md` | princípios + 5 exemplos bons e 5 ruins |
| `personas.md` | 2–3 personas de paciente |
| `pilares.md` | ex.: educação em saúde mental, saúde mental da mulher, psiquiatria intervencionista explicada, bastidores, institucional |
| `identidade-visual/` | logo, paleta, fontes (PENDÊNCIA P5) |
| `normas/` | textos oficiais (CFM, Código de Ética Médica, LGPD, políticas Meta/Google) |
| `proibidos.md` | termos e abordagens vetados |

Regra dura: não inventar dados da Dra. Jessica (CRM, RQE, formação, endereço, preços, procedimentos oferecidos). Campo desconhecido = `TODO:` explícito, listado para perguntar.

---

## 8. Integrações

| Integração | Fase | Modo | Credencial |
|---|---|---|---|
| Telegram (aprovação) | 2 | leitura/escrita no grupo | token do bot do DUDS |
| Google Ads API | 4 | leitura; escrita só com gate | OAuth do DUDS já existente |
| Instagram Graph API (Insights + Content Publishing) | 5 | leitura + publicação com gate | app Meta existente + conta Instagram Profissional vinculada (P3) |
| Google Business Profile / GA4 | 6 (opcional) | leitura | OAuth do DUDS |

---

## 9. Estrutura

```
/root/agencia-revera/
├── CLAUDE.md
├── config/agencia.yaml      # aprovadores, horários, modelos, teto de custo
├── .env                     # chmod 600, fora do git
├── brand/
├── especialistas/<nome>/SKILL.md
├── scripts/                 # transicao.py, render_arte.py, ads_leitura.py, metricas.py, publicar_ig.py, custo.py
├── templates/arte/*.html
├── conteudo/
├── dados/agencia.db         # tabelas: pecas, transicoes, aprovacoes, metricas, custos
├── relatorios/
├── logs/
├── tests/
└── docs/                    # reconhecimento.md, decisoes.md, runbook.md
```
Mais: `AGENTS.md` do perfil do DUDS atualizado com o papel de orquestrador da agência.

---

## 10. Rotinas agendadas (agendador do Hermes; se não houver, systemd timers)

| Quando | O quê |
|---|---|
| Diário 07:00 | coleta de métricas |
| Diário 09:00 | checagem de anomalias no Ads (gasto acima do ritmo, CPC fora do padrão, anúncio reprovado) → alerta |
| Segunda 08:00 | pauta semanal → aprovação |
| Sexta 18:00 | relatório semanal |
| Dia 1, 09:00 | relatório mensal + proposta de calendário |
| Diário 19:45 | resumo curto para a Gutcha incluir no fechamento das 20h |
| Diário 03:00 | backup do `agencia.db` |

---

## 11. Relação com o ecossistema

- Gutcha: recebe resumo diário e escalonamentos de dinheiro. Não orquestra a agência.
- Roberta: leads que querem agendar (DM, comentário, anúncio) são encaminhados a ela. O DUDS nunca agenda, nunca discute caso clínico.
- Nexo e tudo da delegacia: isolamento total. O DUDS não lê nem escreve nada do perfil do Nexo nem de pastas de trabalho policial.

---

## 12. Segurança

- Segredos só em `.env` (600). Nunca imprimir token em chat, log ou commit.
- Nenhum dado de paciente entra no pipeline (LGPD + sigilo médico).
- Pacotes só de PyPI/npm oficiais; nada de repositório de terceiros sem pedir.
- Mudanças cirúrgicas: não refatorar perfis existentes do Hermes.

---

## 13. Fases

**Fase 0 — Reconhecimento (somente leitura, 20–30 min)**
Mapear versão do Hermes e seus mecanismos de subagente, skill e agendamento; localizar o DUDS e suas credenciais (sem exibir valores); checar Python, Node, Playwright, disco e RAM.
Entrega: `docs/reconhecimento.md` + plano com o mecanismo de orquestração escolhido. PARAR.

**Fase 1 — Esqueleto e marca (1–2 h)**
Estrutura de diretórios, `config/agencia.yaml`, `brand/` com TODOs, `SKILL.md` dos 6 especialistas, `AGENTS.md` do DUDS, schema SQLite.
Pronto quando: DUDS responde "qual é seu papel?" descrevendo a agência; `pytest` do schema passa. Perguntar P2.

**Fase 2 — Pipeline, compliance e aprovação (2–3 h)**
`transicao.py`, encadeamento ESTRATEGISTA → REDATOR → COMPLIANCE, bot de aprovação no Telegram.
Pronto quando: peça de teste vai de PAUTA a APROVADO pelo Telegram; os 2 casos de reprovação do compliance passam no teste. Perguntar P1.

**Fase 3 — Design (2 h)**
3 templates (post, carrossel, story), `render_arte.py`, integração ao pipeline.
Pronto quando: peça de teste sai com PNGs nos 3 formatos. Perguntar P5.

**Fase 4 — Tráfego e análise (1–2 h)**
Leitura do Google Ads, gravação de métricas, relatório semanal, alertas.
Pronto quando: relatório de teste com dados reais da conta. Perguntar P4.

**Fase 5 — Instagram (2–3 h, depende de P3)**
Insights + publicação agendada de peças APROVADAS.
Pronto quando: uma peça de teste aprovada é publicada no horário e medida no dia seguinte.

**Fase 6 — Rotinas, custos e runbook (1 h)**
Agendamentos da seção 10, `custo.py`, `docs/runbook.md` (como pausar tudo, reprocessar peça, trocar token). Perguntar P6.

Total estimado: 10–14 h de execução.

---

## 14. Pendências (perguntar só na fase indicada)

| # | Pergunta | Fase |
|---|---|---|
| P1 | Aprovação por grupo de Telegram com Jessica e Fabbro? Jessica usa Telegram? | 2 |
| P2 | Marca principal: perfil pessoal da Dra. Jessica, REVERA ou ambos? CRM/UF e RQE? | 1 |
| P3 | Conta Instagram Profissional, página do Facebook vinculada e permissões no app Meta | 5 |
| P4 | Customer ID do Google Ads e verba mensal | 4 |
| P5 | Logo, paleta e fontes | 3 |
| P6 | Teto mensal de custo de API | 6 |

---

## 15. Regras de trabalho para o Claude Code

1. Uma fase por vez; nunca avançar sem `AVANÇAR`.
2. Declarar suposições antes de implementar; em dúvida, perguntar.
3. Código mínimo; nada especulativo além desta especificação.
4. Toda lógica determinística com teste em `tests/`.
5. Toda decisão de arquitetura registrada em `docs/decisoes.md`.
6. Erros reportados como causa + correção.
7. Em dúvida normativa (CFM, ética médica, LGPD, políticas de anúncio): marcar e perguntar; nunca inventar regra.
