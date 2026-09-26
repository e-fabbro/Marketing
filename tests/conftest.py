import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import db  # noqa: E402

ASSINATURA = "Dra. Jessica Jacomelli — CRM-DF 27043 — RQE 22349"


@pytest.fixture
def raiz(tmp_path):
    """Cópia isolada do projeto: config, brand (com uma norma CFM fictícia), especialistas."""
    for d in ("config", "brand", "especialistas"):
        shutil.copytree(REPO / d, tmp_path / d)
    (tmp_path / "brand" / "normas" / "cfm-2336-2023.md").write_text("Fonte: teste\nNorma CFM de teste.\n", encoding="utf-8")
    (tmp_path / "brand" / "normas" / "cvv-comunicacao-suicidio.md").write_text("Fonte: teste\n", encoding="utf-8")
    for d in ("conteudo", "dados", "logs"):
        (tmp_path / d).mkdir()
    cfg = yaml.safe_load((tmp_path / "config" / "agencia.yaml").read_text(encoding="utf-8"))
    cfg["aprovadores"] = [{"nome": "Fabbro", "telegram_id": 111}, {"nome": "Jessica", "telegram_id": 222}]
    (tmp_path / "config" / "agencia.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return tmp_path


@pytest.fixture
def config(raiz):
    return yaml.safe_load((raiz / "config" / "agencia.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def con(raiz):
    c = db.inicializar(raiz / "dados" / "agencia.db")
    yield c
    c.close()


class FakeCliente:
    """Devolve respostas roteirizadas por especialista (lista consumida em ordem; a última repete)."""

    def __init__(self, respostas: dict[str, list[str]]):
        self.respostas = {k: list(v) for k, v in respostas.items()}
        self.chamadas = []

    def completar(self, modelo, system, user, temperatura, max_tokens):
        nome = system.split("name: agencia-", 1)[1].split("\n", 1)[0].strip()
        self.chamadas.append((nome, modelo, temperatura))
        fila = self.respostas[nome]
        txt = fila.pop(0) if len(fila) > 1 else fila[0]
        return f"```\n{txt}\n```", 100, 50


COPY_OK = f"""# X

## Gancho
Ansiedade não é frescura.

## Corpo
Ansiedade é uma reação do corpo. Quando persiste, merece avaliação psiquiátrica. Cada caso é individual.

## CTA
Salve para reler.

## Assinatura
{ASSINATURA}

## Hashtags
#saudemental #ansiedade

## Notas para o designer
6 slides.
"""

COPY_CURA = COPY_OK.replace("Cada caso é individual.", "Aqui você tem cura garantida em 30 dias.")
COPY_SEM_CRM = COPY_OK.replace(ASSINATURA, "Dra. Jessica")

COMPLIANCE_LLM_OK = """{"resultado": "APROVADO_COMPLIANCE", "itens": [], "trechos_problematicos": [], "recomendacao_ao_redator": "", "motivo_escalar": ""}"""
