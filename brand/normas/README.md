# Normas — textos oficiais (baixados pelo Fabbro; os `.md` são versionados, PDFs não)

O COMPLIANCE decide **só com base nos arquivos desta pasta**, nunca de memória. Enquanto um texto não
estiver aqui, o item correspondente do gate resulta em `ESCALAR`, não em `ok`.

Arquivos esperados (nome sugerido → conteúdo):
- `cfm-2336-2023.pdf|md` — Resolução CFM 2.336/2023 (publicidade médica) e eventuais alterações vigentes
- `codigo-etica-medica.pdf|md` — Código de Ética Médica vigente
- `lgpd.md` — Lei 13.709/2018 (trechos sobre dados sensíveis de saúde)
- `meta-anuncios-saude.md` — política de anúncios de saúde da Meta (texto copiado com data)
- `google-anuncios-saude.md` — política de saúde e medicamentos do Google Ads (texto copiado com data)
- `cvv-comunicacao-suicidio.md` — orientações de comunicação responsável sobre suicídio (fonte oficial)

Cada arquivo deve começar com uma linha `Fonte: <url> — baixado em AAAA-MM-DD`.
Sem o `cfm-2336-2023.md`, toda peça sai `ESCALAR` (a norma de publicidade é pertinente a qualquer peça — D13).
Conversão de PDF: por script (`pypdf`/`pdftotext`), sem redigitar; remover só o timbre repetido por página
e dizer isso no cabeçalho.

Situação (26/09/2026): `cfm-2336-2023.md` ✅ (PDF oficial, 17 páginas) · `cvv-comunicacao-suicidio.md` ✅
(feito na VPS, folheto oficial do CVV) · `lgpd.md` ✅ (texto compilado do Planalto, 26 páginas) ·
`codigo-etica-medica.md`, `meta-anuncios-saude.md`, `google-anuncios-saude.md` `TODO:` Fabbro.
