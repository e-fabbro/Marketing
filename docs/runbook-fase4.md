# Runbook — Fase 4: tráfego e análise

## 1. Instalar e provar a leitura real
```bash
cd /root/agencia-revera && git pull --ff-only && bash scripts/instalar_fase4.sh
```
`metricas.py contas` grava `dados/ads_contas.json` (descoberta pela credencial). Para fixar a conta, copie o
`customer_id` para `config/agencia.yaml → google_ads.contas`. Sem `verba_mensal`, os alertas de ritmo usam o
orçamento diário de cada campanha vindo da API.

## 2. Comandos determinísticos (host ou container)
```bash
PYTHONPATH=vendor python3 scripts/metricas.py coletar --dias 7          # diário 07:00 (Fase 6)
PYTHONPATH=vendor python3 scripts/metricas.py anomalias                  # diário 09:00 → relatorios/alertas_<dia>.md
PYTHONPATH=vendor python3 scripts/metricas.py extrato --de 2026-09-21 --ate 2026-09-27 --md
```

## 3. Relatório semanal (ANALISTA, por delegação)
No Telegram do DUDS (`/new`):

> Gere o relatório semanal da semana de 2026-09-21: rode relatorio.py preparar --tipo semanal --semana 2026-09-21,
> delegue o prompt ao ANALISTA, salve a resposta inteira em relatorios/resposta_analista.md e rode
> relatorio.py entregar --id semanal_2026-09-21 --arquivo relatorios/resposta_analista.md. Mostre o resultado.

Se `entregar` reclamar de "números sem origem nos dados", o DUDS deve delegar de novo passando o erro: a regra é
que nenhum número estimado entra no relatório. Conferir no host:
```bash
head -40 /root/agencia-revera/relatorios/semanal_2026-09-21.md
```
Proposta de tráfego (TRÁFEGO): mesmo ciclo com `relatorio.py preparar --tipo trafego --dias 7` e
`entregar --id trafego_<data>`. A proposta nunca executa nada; mudanças em campanha exigem aprovação (Fase 6 liga o envio).

## 4. Limitações declaradas
- Só Google Ads nesta fase (Instagram entra na Fase 5; GBP/GA4 opcionais na 6).
- `ads_leitura.py` roda no Python do venv do MCP; se o venv mudar de lugar, ajuste `AGENCIA_ADS_PYTHON` no `.env`.
- Contas MCC são listadas mas não coletadas (só contas-cliente).

## 5. Renovar o token do Google Ads (quando `invalid_grant: Token has been expired or revoked`)
Projeto Cloud do cliente OAuth: `project-67c2b7ae-2817-40c5-a3e` (nome gerado automaticamente; procurar por
esse id na busca do console, na conta Google que criou o cliente — a "conta DUDS" ou a do Fabbro).
1. **Parar de expirar**: Google Cloud Console → projeto acima → "Google Auth Platform" → "Audience" → se
   "Publishing status" = Testing, clicar **Publish app**. Em Testing o refresh token expira em 7 dias.
   (Se preferir manter em Testing, a renovação abaixo terá de ser feita toda semana.)
2. **Gerar token novo** na VPS (o script imprime uma URL; abrir no navegador, entrar com a conta DUDS, aceitar;
   o navegador vai para `http://localhost:8080/?code=...` e mostra erro de página — copiar a URL inteira da
   barra de endereços e colar no script quando ele pedir; a entrada fica oculta):
   ```bash
   python3 /root/duds_ads_oauth_headless.py
   ```
3. **Copiar para o perfil do DUDS** (o MCP e a agência leem daqui) e reiniciar o DUDS:
   ```bash
   install -m 600 /root/.config/duds-google-ads/credentials.json /root/.hermes/profiles/duds/secrets/google-ads/credentials.json
   install -m 600 /root/.config/duds-google-ads/env.sh /root/.hermes/profiles/duds/secrets/google-ads/env.sh
   systemctl restart hermes-gateway-duds
   ```
4. **Conferir**: `cd /root/agencia-revera && PYTHONPATH=vendor python3 scripts/metricas.py contas`
   deve listar as contas; depois `bash scripts/instalar_fase4.sh` coleta e imprime o extrato.
