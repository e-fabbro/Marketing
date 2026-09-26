# Fase 0 — Reconhecimento

Data: 2026-09-26. Executado por Claude Code em sessão remota (claude.ai/code), **não na VPS**.

## 0. Limitação central desta execução

Esta sessão roda num container efêmero da Anthropic com o repositório `e-fabbro/Marketing` clonado em
`/home/user/Marketing`. O container **não tem acesso** à VPS `hermes.caixadeprioridades.com.br`.
Consequência: tudo da seção 2 do `CLAUDE.md` que depende do host (Hermes, perfis, DUDS, credenciais,
recursos da máquina) **não pôde ser confirmado**. Foi verificado:

- `/root/.hermes` — não existe neste container.
- `/root/agencia-revera` — não existe neste container.
- Variáveis `DUDS_GOOGLE_ADS_REFRESH_TOKEN`, `TELEGRAM_HOME_CHANNEL` — não definidas aqui.

Para fechar a Fase 0 de verdade, o Fabbro roda na VPS o script somente leitura
`scripts/reconhecimento_vps.sh` (ele mascara segredos: só diz se existem) e cola a saída na conversa.
Com essa saída, a seção 3 abaixo é atualizada e a decisão D1 (`docs/decisoes.md`) é confirmada ou revista.

## 1. O que foi confirmado neste container (referência de toolchain, não da VPS)

| Item | Aqui | Serve de base? |
|---|---|---|
| Python | 3.11.15, pip 24.0 | sim, alvo mínimo 3.11 |
| Node / npm | 22.22.2 / 10.9.7 | sim |
| Playwright | Chromium 1194 em `/opt/pw-browsers`; pacote Python `playwright` **ausente** | na VPS conferir ambos |
| pytest | ausente | instalar de PyPI na Fase 1 |
| PyYAML / Jinja2 / requests | 6.0.1 / 3.1.6 / 2.33.1 | sim |
| SQLite | 3.45.1 (módulo `sqlite3` do Python) | sim |
| Disco / RAM / CPU | 252 GB (30 GB livres) / 15 GB / 4 vCPU | irrelevante; medir na VPS |
| Repositório | vazio (sem commits) antes desta fase; branch `claude/relaxed-ritchie-aw8jye` | — |

## 2. Hermes Agent — mecanismos relevantes (documentação pública, versão `main` em set/2026)

Fonte: docs do projeto NousResearch/hermes-agent (`website/docs/user-guide/...`). A versão instalada na VPS
pode ser anterior; **confirmar com `hermes --version`**.

### 2.1 Perfis
- Diretório `~/.hermes/profiles/<nome>/` com `config.yaml`, `.env`, `SOUL.md`, `memories/`, `skills/`, `state.db`, `cron/`, `profile.yaml`.
- Isolamento por `HERMES_HOME`: `hermes -p duds chat` ou alias `duds chat`. Cada perfil tem skills, cron, `.env` e gateway próprios.
- Regra do projeto: nunca dois processos no mesmo perfil (memória corrompe).
- Divergência com o `CLAUDE.md` seção 2: a doc fala em `SOUL.md`, `skills/`, `cron/`, `state.db`; o `CLAUDE.md`
  presume `AGENTS.md`, `plugins/`, `state/`. **Conferir na VPS qual layout o DUDS realmente usa** antes de editar
  qualquer coisa (o script lista o perfil).

### 2.2 Subagentes (`delegate_task`)
- Ferramenta `delegate_task(goal, context, output_schema, images)`; lote paralelo de até 10 (`delegation.max_concurrent_children`).
- Filho começa com conversa vazia: só recebe `goal`, `context` e os arquivos de contexto do workspace (`AGENTS.md`, `CLAUDE.md`, `.hermes.md`).
- Filho **não** pode: `delegate_task` (salvo `role="orchestrator"` com `max_spawn_depth ≥ 2`), `clarify`, `memory`, `send_message`, `cronjob`. Isso casa com "especialistas não falam com humanos".
- `output_schema` (JSON Schema) com uma rodada de correção — útil para `compliance.json` e `pauta.yaml`.
- Limitações que pesam contra usá-lo como motor dos especialistas:
  - **Um único modelo para todos os filhos** (`delegation.model`), fixado no `config.yaml`. Não há modelo nem temperatura por chamada. A tabela de especialistas pede Opus/Sonnet/Haiku e "temperatura baixa" no COMPLIANCE.
  - **Sem seleção de skill por chamada**: o filho herda só o contexto do workspace. O `SKILL.md` do especialista teria de ir inteiro dentro de `context`.
  - **Custo por especialista** (critério de sucesso 5) não é exposto por chamada; teria de ser inferido.

### 2.3 Skills
- `SKILL.md` com frontmatter (`name`, `description`) + procedimento; carregada sob demanda. Podem viver por perfil em `profiles/<nome>/skills/`. Podem levar scripts junto. Formato exato a confirmar num `SKILL.md` existente na VPS (o script imprime o frontmatter de uma).

### 2.4 Agendamento (cron nativo)
- Ferramenta `cronjob_manage`, comando `/cron add`, CLI `hermes cron create "<agenda>" "<prompt>" [--skill X]`.
- Aceita cron de 5 campos (`0 8 * * 1`), intervalos e linguagem natural.
- Entrega: `deliver="telegram"` (usa `TELEGRAM_HOME_CHANNEL`) ou `deliver="telegram:<chat_id>"`; jobs em `<perfil>/cron/jobs.json`, saídas em `cron/output/`.
- Jobs rodam sob o perfil dono, com o `.env` e toolsets dele. Cobre a seção 10 inteira; systemd só como fallback (backup 03:00 pode ser systemd por ser puro shell).
- Fuso: doc não é explícita. **Testar um job na VPS** e checar `next_run_at` antes de agendar 08:00/18:00.

### 2.5 Telegram
- Gateway por perfil com `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `TELEGRAM_GROUP_ALLOWED_USERS`, `TELEGRAM_GROUP_ALLOWED_CHATS`, `TELEGRAM_HOME_CHANNEL`.
- Grupos: desligar privacy mode no BotFather; `require_mention` configurável; IDs de grupo são negativos.
- Botões inline existem só via ferramenta `clarify` (escolhas), e aprovação de comandos perigosos é por texto "yes".
  Não há API documentada para um **script externo** mandar mensagem com botões pelo gateway.
- Implicação para a seção 6 (botões Aprovar/Ajustar/Descartar por peça, aprovação item a item): o bot de
  aprovação da Fase 2 deve usar a **Bot API do Telegram diretamente** (`python-telegram-bot`, PyPI) com o
  token do DUDS ou um bot dedicado — ver decisão D2. Quem valida o `from.id` contra `aprovadores` é o
  script, não o LLM.

## 3. Itens do CLAUDE.md §2 e o status de confirmação

| Item | Status | Como fechar |
|---|---|---|
| Hermes em `/root/.hermes`, versão | NÃO CONFIRMADO | script §HERMES |
| Layout dos perfis (`AGENTS.md` vs `SOUL.md`, `plugins/`, `state/`) | NÃO CONFIRMADO | script §layout |
| Perfis Gutcha, Nexo, Roberta, Cida, Judite | NÃO CONFIRMADO | script §profiles |
| Onde está o perfil do DUDS | NÃO CONFIRMADO | script §DUDS |
| JSON OAuth Google (Desktop app) no host | NÃO CONFIRMADO | script §DUDS (só caminho) |
| `DUDS_GOOGLE_ADS_REFRESH_TOKEN` | NÃO CONFIRMADO | script (mascarado) |
| `TELEGRAM_HOME_CHANNEL` | NÃO CONFIRMADO | script (mascarado) |
| App Meta existente | NÃO VERIFICÁVEL por script | Fabbro confirma na Fase 5 (P3) |
| Provedor/modelo de LLM do DUDS e chave em `.env` | NÃO CONFIRMADO | script (nomes das vars) — necessário para D1 |
| Python, Node, Playwright, disco, RAM da VPS | NÃO CONFIRMADO | script §RECURSOS/§TOOLCHAIN |

## 4. Plano proposto de orquestração (resumo; detalhe em `docs/decisoes.md`)

**D1 — Especialistas como skills + executor Python determinístico (`scripts/especialista.py`).**
O DUDS continua sendo o único agente Hermes da agência: fala com humanos, dispara o pipeline e responde no
Telegram. Cada especialista é um `especialistas/<nome>/SKILL.md` (papel, entradas, formato de saída,
exemplos, critério de pronto). Quem chama o modelo para cada especialista é um script Python que:
1. monta o prompt = `SKILL.md` + arquivos da marca pertinentes + peça;
2. usa modelo, temperatura e `max_tokens` definidos em `config/agencia.yaml` por especialista;
3. valida a saída (schema de `compliance.json`, `pauta.yaml`);
4. grava tokens e custo em `dados/agencia.db` → tabela `custos` por especialista (critério 5);
5. grava a transição via `scripts/transicao.py` (critério 2: log do compliance é inevitável).

O DUDS invoca o encadeamento pelo terminal (`python3 scripts/pipeline.py --peca <id>`) ou via cron nativo.
`delegate_task` fica como opção para tarefas exploratórias do próprio DUDS, não como motor do pipeline.

**Por que não `delegate_task` como motor:** modelo único para todos os filhos, sem temperatura por chamada,
sem custo por chamada, `SKILL.md` teria de ir colado em `context`. Se a versão da VPS oferecer modelo por
chamada, D1 é revista na Fase 1 — o script de reconhecimento mostra as chaves de `delegation` do `config.yaml`.

**Dependência de D1:** chave de API do provedor de LLM usada pelo DUDS (Anthropic direta ou OpenRouter).
Não foi possível confirmar qual. O executor lê a chave do `.env` da agência; nunca a imprime.

**D2 — Bot de aprovação com Bot API do Telegram direto (Fase 2).** Ver seção 2.5.

**D3 — Agendamento com cron nativo do Hermes no perfil do DUDS; systemd só para o backup.**

## 5. Riscos identificados nesta fase

1. Divergência de layout de perfil (§2.1) pode invalidar suposições da Fase 1 sobre onde escrever o `AGENTS.md` do DUDS.
2. Fuso do cron do Hermes não documentado; horários 08:00/18:00 exigem teste real.
3. Telegram: botões inline por peça não saem do gateway nativo; exige bot próprio (D2), o que pode conflitar com o gateway do DUDS se usarem o **mesmo token** (dois consumidores de `getUpdates` no mesmo bot não funcionam). Opções: bot dedicado da agência, ou webhook. Decidir na Fase 2 junto com P1.
4. Chromium do Playwright na VPS: instalar via PyPI (`playwright`) + `playwright install chromium` — verificar dependências de sistema (libs) e RAM.
