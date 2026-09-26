"""Camada determinística do gate de compliance (sem LLM).

Lê brand/proibidos.md e brand/normas/, aplica regras objetivas ao texto da peça e devolve itens no
formato de compliance.json. Só pode REPROVAR ou ESCALAR; nunca aprova sozinha — o resultado "ok" de um
item aqui significa "nada objetivo encontrado", e a camada LLM (compliance.py) ainda avalia.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

ESPECIALIDADE = re.compile(r"psiquiatr|tratamento|transtorno|depress|ansied|medica[çc][aã]o|antidepress|"
                           r"\bEMT\b|esketamina|\bECT\b|terapia|diagn[óo]stic", re.I)
ASSINATURA = re.compile(r"CRM[-\s]?[A-Z]{2}\s?\d{4,6}.*RQE\s?\d{3,6}", re.I | re.S)
SUICIDIO = re.compile(r"suic[íi]d|autoles|se machucar|tirar a (pr[óo]pria )?vida", re.I)
CVV = re.compile(r"\b188\b")
PROMESSA_PRAZO = re.compile(r"(cura|resultado|melhora|alívio|alivio)[^.\n]{0,40}\b(em|dentro de)\s+\d+\s*(dias?|semanas?|sess[õo]es)", re.I)
PRECO_PROMO = re.compile(r"R\$\s?\d|promo[çc][aã]o|desconto|[úu]ltima[s]? vaga|s[óo] hoje|gr[áa]tis|brinde|sorteio|parcel", re.I)
DEPOIMENTO = re.compile(r"depoimento|antes e depois|antes/depois|minha paciente|meu paciente|relato de (uma|um) paciente", re.I)
NOMES_NORMAS = {1: "cfm", 4: "cfm", 5: "cfm", 6: "cvv", 7: ("meta", "google")}


def _norm(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().casefold()


def carregar_termos_vetados(brand: Path) -> list[str]:
    """Extrai os termos entre aspas da seção 'Termos e padrões vetados' de proibidos.md."""
    texto = (brand / "proibidos.md").read_text(encoding="utf-8")
    inicio = texto.find("## Termos e padrões vetados")
    fim = texto.find("## Abordagens vetadas")
    bloco = texto[inicio:fim if fim > 0 else None]
    termos = []
    for linha in bloco.splitlines():
        if "ESCALAR" in linha:      # linha de preço/promoção: tratada por PRECO_PROMO, vira ESCALAR
            continue
        for grupo in re.findall(r'"([^"]+)"', linha):
            termos += [t.strip() for t in grupo.split("/")]
    return [t for t in termos if len(t) >= 4]


def termo_presente(termo: str, texto_norm: str) -> bool:
    """Casamento por palavra inteira sobre texto normalizado ('cura' não casa em 'frescura')."""
    padrao = r"(?<!\w)" + re.escape(_norm(termo)) + r"(?!\w)"
    return re.search(padrao, texto_norm) is not None


def normas_presentes(brand: Path) -> set[str]:
    pasta = brand / "normas"
    if not pasta.exists():
        return set()
    return {_norm(p.name) for p in pasta.iterdir() if p.is_file() and p.name != "README.md"}


def _tem_norma(presentes: set[str], chave) -> bool:
    chaves = chave if isinstance(chave, tuple) else (chave,)
    return all(any(c in n for n in presentes) for c in chaves)


def avaliar(texto: str, brand: Path, pago: bool = False) -> dict:
    """Devolve {'itens': [...], 'trechos_problematicos': [...], 'resultado': ...} para os itens objetivos."""
    presentes = normas_presentes(brand)
    itens, trechos, escalar_motivos = [], [], []
    t_norm = _norm(texto)

    def item(n, nome, status, just, fonte):
        itens.append({"n": n, "nome": nome, "status": status, "justificativa": just, "fonte": fonte})

    # 1. identificação
    if ESPECIALIDADE.search(texto):
        if "todo" in _norm(texto[-400:]) and "crm" in _norm(texto[-400:]):
            item(1, "identificacao_crm_rqe", "falha", "Assinatura contém TODO (campo não confirmado em brand/marca.md).", "brand/marca.md")
            trechos.append("assinatura com TODO")
        elif not ASSINATURA.search(texto):
            item(1, "identificacao_crm_rqe", "falha", "Peça menciona especialidade/tratamento e não traz nome + CRM/UF + RQE.", "brand/normas/cfm*")
            trechos.append("sem CRM/RQE")
        elif not _tem_norma(presentes, NOMES_NORMAS[1]):
            item(1, "identificacao_crm_rqe", "n/a", "Assinatura presente, mas norma CFM ausente em brand/normas/ para confirmar o formato.", "norma ausente: cfm")
            escalar_motivos.append("norma ausente: cfm")
        else:
            item(1, "identificacao_crm_rqe", "ok", "Assinatura com CRM/UF e RQE encontrada.", "brand/normas/cfm*")
    else:
        item(1, "identificacao_crm_rqe", "n/a", "Peça não menciona especialidade nem tratamento.", "brand/marca.md")

    # 2. promessa / superioridade (termos vetados)
    vetados = [v for v in carregar_termos_vetados(brand) if termo_presente(v, t_norm)]
    m = PROMESSA_PRAZO.search(texto)
    if m:
        vetados.append(m.group(0))
    if vetados:
        item(2, "sem_promessa_resultado", "falha", f"Termos vetados encontrados: {', '.join(sorted(set(vetados)))}.", "brand/proibidos.md")
        trechos += sorted(set(vetados))
    else:
        item(2, "sem_promessa_resultado", "ok", "Nenhum termo vetado de brand/proibidos.md encontrado.", "brand/proibidos.md")

    # 3. diagnóstico/prescrição individual — padrão objetivo mínimo; o resto é do LLM
    m = re.search(r"voc[êe] tem (transtorno|depress|ansiedade generalizada|TDAH|bipolar)", texto, re.I)
    if m:
        item(3, "sem_diagnostico_prescricao", "falha", f"Diagnóstico à distância: '{m.group(0)}'.", "brand/proibidos.md")
        trechos.append(m.group(0))
    else:
        item(3, "sem_diagnostico_prescricao", "ok", "Nenhum padrão objetivo de diagnóstico à distância.", "brand/proibidos.md")

    # 4. dado de paciente / depoimento → ESCALAR (decisão humana), nunca ok automático
    m = DEPOIMENTO.search(texto)
    if m:
        item(4, "sem_dado_paciente", "falha", f"Depoimento/antes-depois/relato: '{m.group(0)}'. Bloqueado por padrão; só com decisão humana.", "brand/normas/cfm*")
        trechos.append(m.group(0))
        escalar_motivos.append("depoimento ou antes/depois exige decisão humana")
    else:
        item(4, "sem_dado_paciente", "ok", "Nenhum padrão objetivo de depoimento ou relato de paciente.", "brand/proibidos.md")

    # 5. preço/promoção → ESCALAR
    m = PRECO_PROMO.search(texto)
    if m:
        item(5, "precos_promocoes", "n/a", f"Menciona preço/promoção ('{m.group(0)}'); regra vigente deve ser conferida por humano.", "brand/normas/cfm*")
        escalar_motivos.append(f"preço/promoção: '{m.group(0)}'")
    else:
        item(5, "precos_promocoes", "n/a", "Peça não cita preço, desconto, sorteio ou brinde.", "brand/normas/cfm*")

    # 6. saúde mental responsável
    if SUICIDIO.search(texto):
        if not CVV.search(texto):
            item(6, "saude_mental_responsavel", "falha", "Tema suicídio/autolesão sem CVV 188.", "brand/proibidos.md")
            trechos.append("tema sensível sem CVV 188")
        elif not _tem_norma(presentes, NOMES_NORMAS[6]):
            item(6, "saude_mental_responsavel", "n/a", "CVV presente; norma de comunicação responsável ausente em brand/normas/.", "norma ausente: cvv")
            escalar_motivos.append("norma ausente: cvv")
        else:
            item(6, "saude_mental_responsavel", "ok", "CVV 188 presente; detalhes de método são avaliados pela camada LLM.", "brand/normas/cvv*")
    else:
        item(6, "saude_mental_responsavel", "ok", "Tema não envolve suicídio/autolesão (avaliação de estigma pela camada LLM).", "brand/proibidos.md")

    # 7. políticas de anúncios
    if pago:
        if _tem_norma(presentes, NOMES_NORMAS[7]):
            item(7, "politicas_anuncios", "ok", "Peça paga; políticas presentes, avaliação detalhada pela camada LLM.", "brand/normas/meta*, google*")
        else:
            item(7, "politicas_anuncios", "n/a", "Peça paga e políticas Meta/Google ausentes em brand/normas/.", "norma ausente: meta/google")
            escalar_motivos.append("norma ausente: políticas de anúncios")
    else:
        item(7, "politicas_anuncios", "n/a", "Peça orgânica.", "-")

    # 8. tom e proibidos (objetivo: nada além do item 2 aqui)
    item(8, "tom_e_proibidos", "ok", "Aderência ao tom avaliada pela camada LLM; termos vetados cobertos no item 2.", "brand/tom-de-voz.md")

    if any(i["status"] == "falha" for i in itens):
        resultado = "REPROVADO"
    elif escalar_motivos:
        resultado = "ESCALAR"
    else:
        resultado = "APROVADO_COMPLIANCE"
    return {"itens": itens, "trechos_problematicos": trechos, "resultado": resultado,
            "motivo_escalar": "; ".join(escalar_motivos)}
