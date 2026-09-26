# Identidade visual — P5

O kit de marca já existe na VPS, em `/root/.hermes/profiles/duds/workspace/referencias-marca-drive/`
(lido em 26/09): `MARCA DAGUA/` (logotipos horizontal, vertical, reduzido, alternativo, ícones, patterns e
`Paleta de Cores cópia 2.png`), `VETORES RGB/{SVG,PDF,JPG,PNG}`, `VETORES CMYK/`, `Papelaria/`.
Referências de carrosséis em `workspace/referencias-carrosseis-drive/` (`inventario.json`,
`estudo-auditoria.json`).

Fase 3 gera aqui, a partir do kit, sem copiar os binários para o git:
- `paleta.yaml` — hex extraído da imagem da paleta, com uso (fundo, texto, destaque). `TODO P5`: confirmar
  os hex com o Fabbro, pois a imagem não traz os códigos em texto.
- `fontes.md` — `TODO P5`: famílias tipográficas não constam no kit listado.
- `logo.svg` — symlink ou cópia do SVG oficial escolhido (qual variante para redes: `TODO P5`).

## Estado em 26/09 (P5 quase fechado)
- `paleta.yaml`: hex oficiais extraídos dos SVGs do Drive (paleta e logotipo). `texto_corpo` e `logo_claro.svg`
  são derivações para legibilidade, marcadas como tal.
- `logo.svg`: Logotipo Horizontal 1 do Drive, sem o fundo e recortado ao conteúdo. A pasta SVG do kit na VPS
  estava vazia; os SVGs vieram do Drive pela sessão do Claude.
- **Fontes** (Fabbro, 26/09): Playfair (regular/bold) para títulos; Poppins (regular/italic/bold) para o resto.
  Assumido *Playfair Display* (Google Fonts, OFL). Arquivos TTF e licenças em `fontes/`, carregados por
  `@font-face` no render, sem depender de fonte instalada no sistema.
