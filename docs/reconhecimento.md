# Fase 0 — Reconhecimento

Data: 2026-09-26. Saída bruta do script somente leitura `scripts/reconhecimento_vps.sh`, executado pelo
Fabbro na VPS (host `Gutcha`), colada na conversa. Nenhum valor de segredo foi exibido.

## 1. Host

| Item | Valor |
|---|---|
| SO | Ubuntu 24.04.4 LTS, kernel 6.8, x86_64, fuso `-03:00` |
| CPU / RAM | 6 vCPU / 7,7 GiB (3,0 em uso, 4,7 disponíveis) |
| Disco | 58 GB, 19 GB livres (67% usado) |
| Python (host) | 3.12.3, pip 24.0, PyYAML ok; **sem** `playwright`, `pytest`, `anthropic` |
| Node | 22.22.2, npm 10.9.7 |
| Playwright browsers | `/root/.cache/ms-playwright/chromium-1243` já baixado (pacote Python ausente) |
| sqlite3 CLI | ausente (módulo Python `sqlite3` basta) |
| Hermes CLI no host | **v0.14.0 (2026.5.16)** — desatualizado em relação aos containers |

## 2. Hermes: como roda de verdade

Os gateways **não rodam no host**: cada perfil é um container Docker via systemd
(`hermes-gateway-<perfil>.service`), imagem `hermes-agent:0.19.0-20260808.1` ou derivada.
O DUDS roda em imagem própria `hermes-agent-duds:images-drive-20260914` (Dockerfile em
`/root/hermes-docker/Dockerfile.duds-images`), com:

- `--memory 2g --cpus 2 --pids-limit 256 --cap-drop ALL`, `/tmp` tmpfs 256 MB;
- **volume: só `/root/.hermes/profiles/duds`** (Gutcha, Cida, Financeiro, Nexo, Perfumista montam `/root` inteiro; DUDS, Roberta e Recepção montam só o próprio perfil);
- `/opt/telegram-bot-api/data` montado somente leitura: o DUDS usa um **servidor local da Bot API do Telegram** (`telegram-bot-api --local`, porta 8081);
- MCPs já em execução dentro do container: `google-ads-mcp` (venv em `profiles/duds/lib/google-ads-mcp/`) e `google-workspace-mcp`, ambos via bridges em `profiles/duds/bin/`;
- houve um OOM do DUDS em 14/09 (`/root/backups-duds-oom-20260914`).

Consequências diretas:

1. **`/root/agencia-revera/` é invisível para o DUDS.** Ou a agência vive dentro de `profiles/duds/`, ou a unit systemd ganha um volume novo (arquivo de sistema → exige pedir). Ver D4.
2. **Comandos `hermes` para o perfil do DUDS devem rodar dentro do container** (`docker exec hermes-gateway-duds python -m hermes_cli.main --profile duds cron list`), não com o CLI 0.14.0 do host.
3. **Chromium/Playwright dentro do container do DUDS é má ideia** (2 GB, `cap-drop ALL`, imagem custom sem deps). Renderização de artes no host. Ver D5.
4. **Pacotes Python novos** não podem ser instalados na imagem sem rebuild. Precedente do perfil Nexo: `vendor/` + `venv/` dentro do perfil. Para a agência: `pip install --target <perfil>/agencia-revera/vendor` no host (mesmo Python 3.12 nos dois lados) e `PYTHONPATH`.

Versões de perfil: perfis usam `SOUL.md` (personalidade) e opcionalmente `AGENTS.md` (Gutcha, Cida, Roberta, Perfumista, Recepção têm). **DUDS tem só `SOUL.md`, sem `AGENTS.md`** — criar é seguro e segue o padrão dos outros perfis. Layout real: `config.yaml`, `.env`, `SOUL.md`, `skills/`, `cron/{jobs.json,executions.db,output/}`, `state.db`, `memories/`, `secrets/`, `plugins/`, `workspace/`, `home/`, `lib/`, `bin/`. O `CLAUDE.md` §2 presumia `plugins/` e `state/`: existem, mas `state/` é interno e skills/cron ficam nas pastas acima.

### 2.1 Perfis existentes (9, não 5)
`carol`, `cida`, `duds`, `financeiro`, `gutcha`, `nexo`, `perfumista`, `recepcao-whatsapp`, `roberta`.
A tabela do `CLAUDE.md` citava Judite: não há perfil com esse nome. Nexo tem gateway próprio com Claude Code montado. **Isolamento do Nexo mantido: nada do Nexo foi lido além do listing.**

### 2.2 DUDS — o que já existe (ler tudo na Fase 1 antes de escrever)
- `config.yaml` com chaves `model`, `delegation`, `approvals`, `security`, `mcp_servers`, `plugins`, `image_gen`, `platforms`.
- `.env` do perfil só tem `HERMES_MEDIA_ALLOW_DIRS`. Token do Telegram e credenciais de provedor de LLM **não estão no `.env`**: provedor vem de `auth.json` (credencial OAuth pooled; `.codex_gpt55_autoraise_notice` sugere OpenAI/Codex via OAuth, não Anthropic) e o Telegram provavelmente em `config.yaml → platforms` ou `secrets/`. **Confirmar na Fase 1 lendo `config.yaml` (sem imprimir valores).**
- **13 skills já instaladas**, sobrepondo os especialistas da especificação:
  - `duds/duds-orquestrador`, `duds/producao-conteudo`, `duds/calendario-editorial`, `duds/pesquisa-pautas`, `duds/conformidade-cfm`, `duds/google-ads-diagnostico`, `duds/modelo-criativos-astra`
  - `compliance/comunicacao-saude-mental-sensivel`, `compliance/comunicacao-segura-saude-mental`, `compliance/automacao-comunicacao-medica`
  - `conteudo/estrategia-editorial-medica`, `conteudo/design-carrosseis-editoriais-medicos`, `conteudo/direcao-arte-editorial`
- Cron do DUDS (listado via `docker exec` em 26/09): **um job ativo**, `pesquisa-diaria-psiquiatria-mulher`,
  agenda `0 11 * * *` (= 08:00 BRT todo dia), entrega `origin`, skills `duds-orquestrador`, `pesquisa-pautas`,
  `conformidade-cfm`; última execução ok em 26/09 11:03 UTC. **Colide com o horário da pauta semanal
  (segunda 08:00).** Na Fase 6, ou a pauta encadeia após a pesquisa (ex.: 08:20), ou a pesquisa de segunda
  alimenta a pauta diretamente. Decidir com o Fabbro.
- `ccb-reels/`, `skill-bundles/`, e um documento de arquitetura anterior em `/home/gutcha-codex/ccb-reel-studio-windows/ARQUITETURA-DUDS.md`.
- Google Ads: `client_secrets.json` em `/root/.config/duds/google-ads/`; `DUDS_GOOGLE_ADS_REFRESH_TOKEN` **vazia no shell** — o token vive em outro lugar (`/root/.config/duds-google-ads/`, `profiles/duds/secrets/` ou o script `/root/duds_ads_set_token.sh`). O MCP `google-ads-mcp` já está rodando com ele, então a credencial funciona; localizar sem exibir na Fase 4.
- `TELEGRAM_HOME_CHANNEL` **vazia no shell** do host; existe nos `.env` de Gutcha, Cida, Financeiro, Nexo, Perfumista e no `.env` global. Para o DUDS, confirmar em `config.yaml`.

### 2.3 Cron nativo
- Funciona por perfil, dentro do container do gateway (ticker a cada minuto; `ticker_heartbeat` atualizado).
- **Horários são armazenados em UTC.** Prova: job global "Fechamento diário 19h" tem `0 22 * * 1-4` e `next_run 22:00+00:00`. Gutcha e Nexo têm chave `timezone:` no `config.yaml`; DUDS não. Ao agendar 08:00 BRT: escrever `0 11 * * 1` ou definir `timezone` no perfil do DUDS e testar.
- `hermes cron create "<agenda>" "<prompt>" --skill <skill>` e entrega `telegram:<chat_id>` confirmados em uso pela Gutcha.

### 2.4 Delegação (`delegate_task`)
Chave `delegation:` presente no `config.yaml` do DUDS (linha 15). Limitações da doc (modelo único para filhos, sem temperatura, sem custo por chamada) valem para 0.19.0 salvo prova contrária. Valores não lidos ainda.

### 2.5 Telegram
- Servidor local `telegram-bot-api --local` na 8081, usado pelo DUDS. Um bot "logado" no servidor local não pode ser usado simultaneamente na API em nuvem, e o gateway já faz polling do token do DUDS. Logo: **um bot dedicado da agência** (API em nuvem, `python-telegram-bot`) é a única forma limpa de ter botões inline sem interferir no DUDS. Reforça D2.
- Processo host: bot de aprovação roda no host (systemd), lê/escreve `agencia.db` no perfil (bind mount do mesmo kernel → SQLite seguro).

### 2.6 Outros serviços no host (não tocar)
`hermes-gateway.service` (Gutcha, default), `hermes-dashboard` (9119), `hermes-webhook` (8001), `office-gutcha`, nginx 80/443, `/opt/perse` (8080), timers `hermes-monitor` (5 min), `hermes-backup` (diário ~03:19, faz backup de `/root/.hermes` → cobre a agência se ela viver no perfil), `hermes-purga-sessoes-recepcao`, `drcc-sync`.

## 3. Itens do CLAUDE.md §2 — status

| Item | Status | Observação |
|---|---|---|
| Hermes em `/root/.hermes` | CONFIRMADO | CLI host 0.14.0; gateways em Docker 0.19.0 |
| Layout `AGENTS.md`, `config.yaml`, `plugins/`, `state/` | PARCIAL | `SOUL.md` + `AGENTS.md` opcional; skills em `skills/`, cron em `cron/` |
| Gutcha, Nexo, Roberta, Cida, Judite | PARCIAL | Judite não existe; há também carol, financeiro, perfumista, recepcao-whatsapp |
| Perfil do DUDS | CONFIRMADO | `/root/.hermes/profiles/duds`, gateway `hermes-gateway-duds.service` |
| OAuth Google Desktop app (JSON) | CONFIRMADO | `/root/.config/duds/google-ads/client_secrets.json` |
| `DUDS_GOOGLE_ADS_REFRESH_TOKEN` | NÃO no shell | credencial em uso pelo MCP; localizar na Fase 4 |
| `TELEGRAM_HOME_CHANNEL` | NÃO no shell | existe nos `.env` dos perfis; DUDS a confirmar em `config.yaml` |
| App Meta existente | CONFIRMADO indiretamente | vars `WHATSAPP_CLOUD_*` nos `.env` de Gutcha e Recepção |
| Escopo de escrita `/root/agencia-revera` | **INVÁLIDO como está** | invisível ao DUDS; ver D4 |

## 4. Plano de orquestração (resumo; detalhe em `docs/decisoes.md`)

- **D1 (revista):** especialistas como `SKILL.md` + executor Python determinístico. **Depende de P0**: qual provedor de LLM os especialistas usam. O DUDS parece rodar em OAuth OpenAI/Codex (sem chave de API no `.env`), o que um script não consegue usar diretamente. Opções: (a) chave Anthropic dedicada da agência (modelos por especialista como a tabela pede, custo rastreado por tokens); (b) `hermes proxy` (proxy OpenAI-compatível local para provedores OAuth) — mesmo provedor do DUDS, sem modelo por especialista; (c) `delegate_task` — mais simples, sem modelo/temperatura por especialista nem custo por chamada.
- **D2 (mantida):** bot de aprovação dedicado, processo no host.
- **D3 (mantida, ajustada):** cron nativo no perfil do DUDS, horários em UTC ou `timezone` configurado; backup diário já coberto por `hermes-backup.timer` se a agência viver no perfil.
- **D4 (nova):** agência em `/root/.hermes/profiles/duds/agencia-revera/` (dentro do escopo já autorizado), com symlink `/root/agencia-revera` no host.
- **D5 (nova):** renderização de artes (Playwright) e bot de aprovação rodam **no host**, não no container.

## 4.1 Respostas do Fabbro (26/09)
- P0 provedor: "mesmo do DUDS, ChatGPT" → D1 aceita na opção (b).
- Localização: "VPS" → D4 adotada por padrão (dentro do perfil, symlink), sem editar systemd.
- Leitura de `config.yaml`, skills, `jobs.json` e `ARQUITETURA-DUDS.md`: "não sei" → o `CLAUDE.md` só
  restringe escrita (e qualquer acesso ao Nexo); leitura sem exibir segredos será feita na Fase 1.

- P2 (26/09, na abertura da Fase 1): CRM 27043, RQE 22349. Faltam UF do CRM e marca principal → `TODO`.

## 4.2 Leitura do perfil do DUDS (26/09, `scripts/ler_contexto_duds.sh`, valores mascarados)
- **Provedor/modelos**: `openai-codex` via `chatgpt.com/backend-api/codex`; padrão `gpt-5.6-terra`;
  `delegation.model: gpt-6-astra`. Skill `modelo-criativos-astra` fixa: Terra para texto, Astra só para
  visual. Imagem: plugin `image_gen/duds-sunburst` (`gpt-image-2.5-sunburst-high`).
- **Telegram**: modo local (`base_url http://127.0.0.1:8081/bot`), `allow_from` 5326591280 (Eduardo) e
  2085222248; `home_channel` = DM do Eduardo. O cron existente entrega no grupo **"Marketing - Duds"**
  (`chat_id -5238127555`) — já existe um grupo de marketing; candidato natural ao canal de aprovação (P1).
- **Fatos de marca com fonte**: Dra. Jessica **Jacomelli**, **CRM-DF 27043, RQE 22349**, psiquiatra em
  **Brasília**, presencial e telemedicina, **marca pessoal** (SOUL.md, profile.yaml e prompt do cron).
- **Skills**: 13, com `duds-orquestrador` como entrada, protocolo `APROVADO <nome-da-peça>` literal,
  `conformidade-cfm` com `references/checklist.md` e busca web da norma vigente. Há também
  `workspace/AGENTS.md` (3,3 KB, regras de marca: pilares, CTAs, DoD) que o orquestrador lê — **ainda não
  lido; ler antes da Fase 2** para alinhar `brand/pilares.md`. `workspace/referencias-marca-drive/` e
  `referencias-carrosseis-drive/` existem → insumo para P5 (identidade visual).
- **MCPs**: `google-workspace` e `google-ads` ativos no container (bridges em `bin/`).
- **Arquitetura anterior (ARQUITETURA-DUDS.md, 06/09)**: estúdio de reels no host, usuário
  `gutcha-codex`, API HTTP em `127.0.0.1:8765` (porta confirmada em escuta), DUDS fala com ela pela
  rede do host. Precedente direto para D5: serviços pesados no host, contrato por HTTP local ou por
  pasta bind-mounted. O orquestrador atual diz que o editor de vídeo está desativado.

## 4.3 Fase 1 — critério de pronto
`pytest` do schema passou na VPS (9 testes, 26/09). O teste "qual é o seu papel?" no Telegram **não foi
verificado**: o Fabbro mandou `AVANÇAR` sem colar a resposta do DUDS. Pendente de confirmação.

## 4.4 Fase 2/3 — achados da VPS (26/09, noite)
- `hermes proxy` (0.19): upstreams só `nous` e `xai`; porta padrão 8645. Não serve para `openai-codex` → D1 vai
  para delegação (c).
- `render_arte.py` não achou o Chromium no host: o kit do Playwright em `/root/.cache/ms-playwright` usa
  provavelmente `chrome-linux64/`; busca ampliada (glob `chrome-linux*` + varredura). Confirmar na reinstalação.
- `referencias-marca-drive/VETORES RGB/SVG/` está **vazia**; logotipo virá de PNG (`MARCA DAGUA/` ou `VETORES RGB/PNG/`).
- Bot de aprovação ainda sem token; ponta a ponta pelo Telegram não executado.

## 4.5 Fase 3 — critério de pronto (26/09, 11:40 BRT)
Cumprido na VPS: `chrome-headless-shell` 1243 encontrado, 50 testes passaram, peças de teste renderizadas em
1080x1080, 1080x1350 (3 slides) e 1080x1920. Serviço de render respondeu `/saude`. Pendências da Fase 3:
P5 (hex, fontes, logotipo) e a unit systemd do render.

## 4.6 Fase 2 — ciclo de delegação validado na VPS (26/09, 15:02 BRT)
Peça `2026-10-01_teste-delegacao` operada pelo DUDS via `passo`/`entregar` + `delegate_task`:
REDATOR → DESIGNER (1ª resposta com 0 slides, rejeitada pela validação e refeita com o erro no prompt) →
render pelo serviço do host (`arte_01.png`, `arte_02.png`) → COMPLIANCE regras + LLM → **ESCALAR** por norma
ausente (`brand/normas/` vazio). O DUDS respeitou a máquina de estados e não usou o prompt antigo quando
`passo` devolveu `fim`. Bug encontrado e corrigido no caminho: migração da coluna `custos.estimado`.
Observação: o DUDS criou para si uma skill `agencia-revera-pipeline` a partir do AGENTS.md (no perfil dele).
Falta para o critério de pronto da Fase 2: decisão humana pelo bot no Telegram (token do bot ainda ausente).

## 4.7 Fase 2 — critério de pronto cumprido (26/09, 12:24 BRT)
Bot dedicado no grupo "Marketing - Duds": peça `2026-10-01_teste-delegacao` foi de ESCALAR → Liberar →
AGUARDANDO_HUMANO → **APROVADO** pelo botão, com `aprovacoes` = APROVAR por 5326591280. Dois bugs
encontrados e corrigidos no caminho (CHECK sem LIBERAR em banco antigo; decisão não atômica). O clique
"Liberar" anterior à correção ficou só em `transicoes` (autor telegram:5326591280), não em `aprovacoes`.
Pendentes da Fase 2: P1 (Jessica no grupo), `brand/normas/`, unit systemd do bot.

## 5. Riscos

1. RAM: 7,7 GiB para 9 gateways + dashboard + nginx + bridges. Chromium no host durante render: ~300–500 MB por instância; renderizar uma arte por vez.
2. Versão do CLI do host (0.14.0) diverge dos containers (0.19.0): nunca operar o perfil do DUDS com o CLI do host.
3. Skills existentes do DUDS podem conflitar com as novas (nomes, gatilhos). Fase 1 começa lendo as 13.
4. Cron em UTC: erro de fuso publica pauta às 05:00.
5. Credencial OAuth ChatGPT usada por um executor automatizado: limites de taxa da assinatura podem
   travar o pipeline em horário de pico; sem preço por token, o teto de custo vira teto de tokens.
6. Nexo montado com `/root` inteiro e Claude Code: a agência dentro de `profiles/duds/` fica legível pelo Nexo (leitura). Não é violação da regra (que proíbe o DUDS ler o Nexo), mas registrado.
