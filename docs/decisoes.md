# Registro de decisões de arquitetura

Formato: ID, data, status (proposta | aceita | revista), contexto, decisão, consequências.

## D1 — Mecanismo de orquestração dos especialistas
- Data: 2026-09-26 · Status: **aceita (opção c), revista à noite de 26/09** — Fabbro: "mesmo do DUDS, ChatGPT"; proxy descartado
- Contexto: `CLAUDE.md` §3 manda usar subagentes/skills nativos se existirem. Hermes 0.19.0 tem
  `delegate_task`, mas com modelo único para os filhos, sem temperatura por chamada, sem custo por chamada
  e sem seleção de skill por chamada. Os critérios de sucesso 2 e 5 exigem log de compliance inevitável e
  custo por especialista. Reconhecimento mostrou que o DUDS não tem chave de API no `.env`; o provedor vem
  de `auth.json` (OAuth), o que um script externo não consome diretamente.
- Decisão (condicional): especialistas são `especialistas/<nome>/SKILL.md` executadas por
  `scripts/especialista.py`, que monta o prompt (SKILL.md + marca + peça), chama o provedor configurado em
  `config/agencia.yaml`, valida a saída e grava custo e transição em `dados/agencia.db`. O DUDS orquestra
  (dispara `scripts/pipeline.py`, fala com humanos). O provedor por trás do executor é o item **P0**:
  - (a) chave Anthropic dedicada → modelos por especialista como na tabela; custo por tokens. Descartada pelo Fabbro (26/09).
  - (b) `hermes proxy` → reaproveita a credencial OAuth do DUDS; um único modelo; custo estimado, não medido.
  - (c) `delegate_task` puro → sem executor; sem modelo/temperatura por especialista; custo não atribuível.
- Resolução de P0: os especialistas usam a mesma credencial OAuth ChatGPT do DUDS. Caminho técnico a
  validar na Fase 2, nesta ordem: (1) `hermes proxy` do perfil do DUDS (endpoint OpenAI-compatível local),
  o executor Python chama esse endpoint e escolhe modelo por especialista dentro do que a credencial
  permite; (2) se o proxy não puder coexistir com o gateway no mesmo perfil, o DUDS invoca os especialistas
  por `delegate_task`, com o `SKILL.md` embutido em `context` e `output_schema` para as saídas
  estruturadas. Em ambos os casos o modelo real é da família GPT-5, não Opus/Sonnet/Haiku: a coluna
  "modelo sugerido" do `CLAUDE.md` vira só uma ordem de prioridade (tarefas críticas → modelo maior).
- Refinamento após ler o perfil (26/09): modelos disponíveis `gpt-5.6-terra` (texto) e `gpt-6-astra`
  (visual). `delegate_task` está fixado em Astra para todos os filhos, o que contraria a regra da skill
  `modelo-criativos-astra` para texto; por isso a ordem de teste na Fase 2 é proxy primeiro. Tabela por
  especialista já em `config/agencia.yaml`.
- Revisão final (26/09, `testar_llm.sh`): `hermes proxy` 0.19 só tem upstreams `nous` e `xai`; a credencial
  ChatGPT (`openai-codex`) não passa por ele. Caminho (b) descartado. **Adotado (c)**: o DUDS chama
  `delegate_task` por especialista; `pipeline.py passo/entregar` é o motor de passos determinístico que
  prepara o prompt (SKILL.md + marca + peça), recebe a resposta, valida, grava e avança o estado. O modo
  direto (`AGENCIA_LLM_BASE_URL`) fica no código para um endpoint futuro, sem uso hoje.
- Custo (critério 5): assinatura ChatGPT não fatura por token e `delegate_task` não devolve `usage`.
  `custos` registra tokens **estimados** (chars/4, coluna `estimado=1`) por especialista; o teto em
  `config/agencia.yaml` é em tokens/mês sobre essa estimativa. Limitação declarada: o critério 5 é
  atendido de forma aproximada, não medida.
- Consequências: pipeline testável com `pytest` fora do Hermes (LLM mockado); dependências Python em
  `vendor/` dentro do perfil (precedente do Nexo), pois a imagem do DUDS não aceita `pip install`
  persistente.

## D2 — Bot de aprovação no Telegram
- Data: 2026-09-26 · Status: **proposta** (decidir na Fase 2 com P1)
- Contexto: o DUDS usa servidor local `telegram-bot-api --local` e já faz polling do próprio token; o gateway
  só tem botões via `clarify`. Reutilizar o token do DUDS quebra o gateway.
- Decisão: bot dedicado da agência (`python-telegram-bot`, API em nuvem), processo systemd **no host**,
  validando `from.id` contra `config/agencia.yaml → aprovadores` e gravando em `aprovacoes` via
  `transicao.py`. Alternativa mais simples, se o Fabbro preferir: comandos de texto pelo próprio DUDS
  (`aprovar <id>`), sem botões e com o LLM no caminho da aprovação — menos seguro.
- Refinamento (26/09): já existe o grupo Telegram "Marketing - Duds" (`-5238127555`) com o Eduardo e o
  DUDS, e o protocolo textual `APROVADO <nome-da-peça>` das skills atuais. O bot dedicado entra nesse
  grupo; o protocolo textual continua para rascunhos avulsos e não move estado do pipeline.
- Consequências: mais um bot no BotFather; aprovações formais só valem pelo bot da agência.

## D3 — Agendamento
- Data: 2026-09-26 · Status: **proposta**
- Decisão: rotinas da §10 no cron nativo do Hermes, no perfil do DUDS, criadas de dentro do container
  (`docker exec hermes-gateway-duds python -m hermes_cli.main --profile duds cron create ...`).
  Horários gravados em UTC (confirmado no reconhecimento) → 08:00 BRT = `0 11 * * 1`.
  Backup de `agencia.db`: coberto por `hermes-backup.timer` já existente se a agência viver no perfil (D4);
  timer systemd próprio só se o Fabbro quiser cópia separada.
- Consequências: conferir `cron/jobs.json` do DUDS antes de criar jobs; testar um job de 1 minuto.

## D4 — Localização da agência
- Data: 2026-09-26 · Status: **aceita por padrão** — Fabbro respondeu "VPS", sem escolher entre as duas
  opções; adotada a que não toca arquivo de sistema. Reversível na Fase 1 se ele preferir a unit systemd.
- Contexto: o container do DUDS monta só `/root/.hermes/profiles/duds`; `/root/agencia-revera/` seria
  invisível ao agente. Alterar a unit systemd é arquivo de sistema (exige pedir) e reinicia o gateway.
- Decisão: repositório em `/root/.hermes/profiles/duds/agencia-revera/` (já dentro do escopo de escrita
  autorizado); symlink `/root/agencia-revera → profiles/duds/agencia-revera` no host para conveniência.
  `.env` da agência com `chmod 600` dentro dessa pasta, fora do git.
- Consequências: caminho único visível de host e container; backup automático pelo `hermes-backup.timer`;
  legível pelo Nexo (monta `/root`) — aceito, é leitura e não há dado de paciente.

## D5 — Processos que rodam no host, não no container
- Data: 2026-09-26 · Status: **proposta**
- Contexto: container do DUDS tem 2 GB, `cap-drop ALL`, imagem custom sem Chromium; OOM em 14/09.
- Decisão: `render_arte.py` (Playwright/Chromium) e o bot de aprovação (D2) rodam no host como serviços
  systemd. Interface com o DUDS pelo sistema de arquivos e pelo `agencia.db` (bind mount, mesmo kernel).
  Render: o pipeline grava `conteudo/<peça>/render.request`; serviço no host (path unit ou timer de 1 min)
  renderiza e grava `arte*.png`; uma arte por vez.
- Precedente (ARQUITETURA-DUDS.md, 06/09): o estúdio de reels já segue este desenho (serviço no host,
  API em `127.0.0.1:8765`, DUDS acessa pela rede do host). Se o contrato por pasta se mostrar frágil,
  migrar para HTTP local no mesmo molde.
- Consequências: dois serviços novos no host (pedir antes de instalar units); Playwright instalado no host
  via PyPI (`playwright`), reaproveitando Chromium já em `~/.cache/ms-playwright`.

## D6 — Instalação no perfil do DUDS sem tocar arquivos existentes
- Data: 2026-09-26 · Status: **aceita**
- Contexto: o DUDS tem `SOUL.md` mas não `AGENTS.md`; outros perfis usam `AGENTS.md` para instruções
  operacionais. A imagem Docker do DUDS não aceita `pip install` persistente.
- Decisão: `AGENTS.md` do DUDS é um **symlink** para `agencia-revera/duds/AGENTS.md` (versionado), criado
  por `scripts/instalar_fase1.sh` apenas se o alvo não existir. `SOUL.md`, `config.yaml` e skills
  existentes não são alterados na Fase 1. Dependências Python em `vendor/` (`pip install --target`),
  carregadas com `PYTHONPATH=vendor` — mesmo Python 3.12 no host e no container.
- Consequências: atualizar o `AGENTS.md` é `git pull`; as 13 skills existentes do DUDS continuam ativas
  e serão reconciliadas com as seis novas depois da leitura de `scripts/ler_contexto_duds.sh`.

## D7 — Gate de compliance em duas camadas
- Data: 2026-09-26 · Status: **aceita**
- Contexto: o critério de sucesso 2 exige que o gate seja inevitável e comprovável em log; o teste
  obrigatório da §5 ("cura garantida em 30 dias" e peça sem CRM/RQE reprovadas) precisa ser determinístico.
- Decisão: `compliance_regras.py` (sem LLM) aplica regras objetivas a partir de `brand/proibidos.md` e
  `brand/normas/` (termos vetados por palavra inteira, assinatura CRM/UF+RQE, promessa com prazo, preço →
  ESCALAR, depoimento → REPROVADO, suicídio sem CVV → REPROVADO, norma ausente → ESCALAR). A camada LLM
  (`especialistas/compliance/SKILL.md`) roda depois e só pode endurecer o resultado. `transicao.py` não
  permite chegar a AGUARDANDO_HUMANO sem passar por COMPLIANCE.
- Consequências: 38 testes cobrem estado, gate, pipeline com LLM simulado e aprovação; a camada LLM sem
  proxy funcional não bloqueia a Fase 2 (`--sem-llm`), mas o gate normativo fica em ESCALAR até
  `brand/normas/` ter os textos.

## D8 — Decisões humanas sobre peças escaladas
- Data: 2026-09-26 · Status: **aceita**
- Decisão: peça em ESCALAR vai ao mesmo grupo com botões *Liberar p/ aprovação* (→ AGUARDANDO_HUMANO),
  *Ajustar* (→ RASCUNHO) e *Descartar*; a decisão fica em `aprovacoes` com `decisao=LIBERAR`. Não existe
  APROVAR direto de ESCALAR: a peça liberada ainda passa pela aprovação normal.

## D9 — Motor de render das artes
- Data: 2026-09-26 · Status: **aceita**
- Contexto: o `CLAUDE.md` pede templates HTML/CSS renderizados em PNG com Playwright. O pacote Python
  `playwright` não está no host nem no container, mas os binários do Playwright já estão em
  `~/.cache/ms-playwright` (chromium e chromium_headless_shell). No Chrome com `--headless=new`, o viewport
  perde ~87 px da "moldura" e a arte sai deslocada (medido: janela 1080x1350 → viewport 1080x1263).
- Decisão: `render_arte.py` usa o `chromium_headless_shell` do Playwright pela linha de comando
  (`--window-size` + `--screenshot`), sem o pacote Python; verifica o viewport antes de renderizar e falha
  se não bater. Templates Jinja2 em `templates/arte/` (post, carrossel, story) com cores e fontes de
  `brand/identidade-visual/paleta.yaml`. Serviço HTTP `render_servico.py` no host (porta 8766, um render por
  vez), no molde do estúdio de reels; dentro do container o pipeline usa `AGENCIA_RENDER_URL`.
- Consequências: zero dependência nova pesada; se um dia o `headless_shell` sumir do host, o erro é explícito
  e a correção é `pip install playwright && playwright install chromium`.
