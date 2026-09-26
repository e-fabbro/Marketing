# Runbook — Fase 2: pipeline, compliance e aprovação

Tudo abaixo roda na VPS. `RAIZ=/root/.hermes/profiles/duds/agencia-revera` (ou `/root/agencia-revera`).
Prefixo dos scripts: `cd $RAIZ && PYTHONPATH=vendor python3 scripts/<x>.py`.

## 1. Instalar
```bash
cd /root/agencia-revera && git pull --ff-only && bash scripts/instalar_fase2.sh
```

## 2. Endpoint dos especialistas (D1b — hermes proxy do DUDS)
```bash
bash scripts/testar_llm.sh
```
Se o passo 1 mostrar como subir o proxy no perfil do DUDS, subir **dentro do container** e em segundo plano, por
exemplo (ajustar conforme o `--help`):
```bash
docker exec -d hermes-gateway-duds python -m hermes_cli.main --profile duds proxy --host 127.0.0.1 --port 8788
```
Depois ajustar `AGENCIA_LLM_BASE_URL` no `.env` e repetir o teste até o passo 5 responder "ok".
Se o proxy não existir ou não coexistir com o gateway: caminho (2) de D1 — o DUDS chama os especialistas por
`delegate_task`; avisar aqui para eu adaptar `especialista.py`.

## 3. Bot de aprovação (D2)
1. BotFather: `/newbot` → nome sugerido "Agência REVERA — aprovações"; copiar o token para `.env`
   (`AGENCIA_TELEGRAM_BOT_TOKEN=`); `chmod 600 .env`. Desligar privacy mode: `/setprivacy` → Disable.
2. Adicionar o bot ao grupo "Marketing - Duds" (chat_id `-5238127555`, já em `config/agencia.yaml`).
3. Teste em primeiro plano (Ctrl+C para parar):
   ```bash
   cd /root/agencia-revera && PYTHONPATH=vendor python3 scripts/bot_aprovacao.py
   ```
   No grupo: `/id` (confirma seu `telegram_id` e o `chat_id`), `/pendentes`.
4. Só depois, como serviço (exige autorização; arquivo de sistema):
   ```bash
   cp deploy/agencia-bot-aprovacao.service /etc/systemd/system/ && systemctl daemon-reload
   systemctl enable --now agencia-bot-aprovacao && systemctl status agencia-bot-aprovacao --no-pager
   ```

## 4. Teste ponta a ponta sem LLM (prova o estado, o gate e a aprovação)
```bash
cd /root/agencia-revera && export PYTHONPATH=vendor
python3 scripts/transicao.py criar --id 2026-09-30_teste-fase2 --canal instagram --formato post --pilar 3 \
  --objetivo alcance --cta "Salve." --autor fabbro
cat > conteudo/2026-09-30_teste-fase2/copy.md <<'MD'
# 2026-09-30_teste-fase2

## Gancho
Ansiedade não é frescura.

## Corpo
Ansiedade é uma reação do corpo. Quando persiste, merece avaliação psiquiátrica. Cada caso é individual.

## CTA
Salve.

## Assinatura
Dra. Jessica Jacomelli — CRM-DF 27043 — RQE 22349

## Hashtags
#saudemental

## Notas para o designer
1 slide.
MD
python3 scripts/transicao.py mover --peca 2026-09-30_teste-fase2 --para RASCUNHO --autor duds
python3 scripts/transicao.py mover --peca 2026-09-30_teste-fase2 --para ARTE --autor duds --motivo "sem arte (Fase 3)"
python3 scripts/transicao.py mover --peca 2026-09-30_teste-fase2 --para COMPLIANCE --autor duds
python3 scripts/compliance.py --peca 2026-09-30_teste-fase2 --sem-llm
```
- Sem textos em `brand/normas/`: resultado `ESCALAR` (norma ausente). Com `cfm-*.md` presente: `APROVADO_COMPLIANCE`.
- Mova para o resultado impresso e, se `APROVADO_COMPLIANCE`, para `AGUARDANDO_HUMANO`:
```bash
python3 scripts/transicao.py mover --peca 2026-09-30_teste-fase2 --para APROVADO_COMPLIANCE --autor compliance
python3 scripts/transicao.py mover --peca 2026-09-30_teste-fase2 --para AGUARDANDO_HUMANO --autor duds
```
- Em até 30 s o bot posta no grupo com os botões. Clique **Aprovar**. Depois:
```bash
python3 scripts/transicao.py estado --peca 2026-09-30_teste-fase2      # esperado: APROVADO
python3 - <<'PY'
import sys; sys.path.insert(0,'scripts'); import db
c=db.conectar('dados/agencia.db'); print([dict(r) for r in c.execute("SELECT peca_id,decisao,telegram_id FROM aprovacoes")])
PY
```
- Tentar aprovar por um ID fora da lista (ou pela CLI com `--autor duds`) deve falhar com `ERRO transição`.

## 5. Teste com LLM (depois do passo 2)
```bash
python3 scripts/transicao.py criar --id 2026-10-01_teste-llm --canal instagram --formato carrossel --pilar 2 \
  --objetivo salvamentos --cta "Salve." --autor fabbro
python3 scripts/pipeline.py peca --peca 2026-10-01_teste-llm        # REDATOR → gate (regras + LLM) → AGUARDANDO_HUMANO
python3 scripts/pipeline.py pauta --semana 2026-10-05 --criar        # ESTRATEGISTA → conteudo/pauta_2026-10-05.yaml + peças
```

## 6. Pausar / reprocessar
- Pausar aprovações: `systemctl stop agencia-bot-aprovacao`. Nada é aprovado sem ele.
- Reprocessar peça reprovada/escalada: decisão humana pelo bot (Ajustar/Descartar/Liberar) ou
  `transicao.py mover --autor telegram:<seu id>`. Depois `pipeline.py peca --peca <id>`.
- Logs: `logs/pipeline.log`, `logs/especialista.log`, `logs/bot_aprovacao.log`.
