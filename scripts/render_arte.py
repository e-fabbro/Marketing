#!/usr/bin/env python3
"""DESIGNER (parte determinística): renderiza conteudo/<peça>/arte.yaml em PNGs com os templates HTML/CSS
da marca e o Chromium headless do Playwright (binário já baixado em ~/.cache/ms-playwright).

  python3 scripts/render_arte.py --peca <id>            # grava conteudo/<id>/arte_01.png, arte_02.png, ...
  python3 scripts/render_arte.py --validar --peca <id>  # só valida o arte.yaml (sem Chromium)

Roda NO HOST (D5). Dentro do container do DUDS não há Chromium; o pipeline usa o serviço HTTP
(render_servico.py) quando AGENCIA_RENDER_URL está no .env, senão renderiza localmente.
"""
from __future__ import annotations

import argparse
import base64
import glob
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import RAIZ, carregar_env, logger  # noqa: E402

FORMATOS_POR_TEMPLATE = {"post": {"1080x1080", "1080x1350"}, "carrossel": {"1080x1350", "1080x1080"}, "story": {"1080x1920"}}
SLIDES_POR_TEMPLATE = {"post": (1, 1), "story": (1, 1), "carrossel": (2, 8)}
MAX_TITULO, MAX_CORPO = 60, 220


class ArteInvalida(Exception):
    pass


def validar(arte: dict) -> None:
    t = arte.get("template")
    if t not in FORMATOS_POR_TEMPLATE:
        raise ArteInvalida(f"template desconhecido: {t}")
    formatos = arte.get("formatos") or []
    if not formatos or not set(formatos) <= FORMATOS_POR_TEMPLATE[t]:
        raise ArteInvalida(f"formatos {formatos} incompatíveis com template {t}; permitidos: {sorted(FORMATOS_POR_TEMPLATE[t])}")
    slides = arte.get("slides") or []
    lo, hi = SLIDES_POR_TEMPLATE[t]
    if not (lo <= len(slides) <= hi):
        raise ArteInvalida(f"template {t} exige entre {lo} e {hi} slides; recebidos {len(slides)}")
    for i, s in enumerate(slides, 1):
        if not s.get("titulo") or not s.get("corpo"):
            raise ArteInvalida(f"slide {i}: titulo e corpo são obrigatórios")
        if len(s["titulo"]) > MAX_TITULO:
            raise ArteInvalida(f"slide {i}: título com {len(s['titulo'])} caracteres (máx. {MAX_TITULO})")
        if len(s["corpo"]) > MAX_CORPO:
            raise ArteInvalida(f"slide {i}: corpo com {len(s['corpo'])} caracteres (máx. {MAX_CORPO})")
    if not (arte.get("assinatura") or "").strip():
        raise ArteInvalida("assinatura obrigatória")
    if "TODO" in arte["assinatura"]:
        raise ArteInvalida("assinatura contém TODO")
    if not (arte.get("alt_text") or "").strip():
        raise ArteInvalida("alt_text obrigatório")


def carregar_paleta(raiz: Path) -> dict:
    p = raiz / "brand" / "identidade-visual" / "paleta.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _logo_uri(raiz: Path, paleta: dict) -> str:
    rel = (paleta.get("logo") or "").strip()
    if not rel:
        return ""
    p = raiz / rel
    if not p.exists():
        return ""
    mime = "image/svg+xml" if p.suffix.lower() == ".svg" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def _corpo_html(corpo: str, destaque: str | None) -> Markup:
    seguro = html.escape(corpo)
    if destaque and destaque.strip():
        d = html.escape(destaque.strip())
        seguro = seguro.replace(d, f"<mark>{d}</mark>", 1)
    return Markup(seguro)   # já escapado acima; Markup evita o segundo escape do autoescape


def encontrar_chromium() -> str:
    """Prefere o chromium_headless_shell do Playwright: nele o viewport é exatamente --window-size.
    No Chrome com --headless=new o viewport perde ~87px de "moldura" e a arte sai deslocada."""
    env = carregar_env()
    cand = [env.get("AGENCIA_CHROMIUM", ""), os.environ.get("AGENCIA_CHROMIUM", "")]
    bases = [Path.home() / ".cache" / "ms-playwright", Path("/root/.cache/ms-playwright"), Path("/opt/pw-browsers")]
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        bases.insert(0, Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]))
    # layouts do Playwright: antigo chrome-linux/headless_shell; recente chrome-headless-shell-linux64/chrome-headless-shell
    for base in bases:
        cand += sorted(glob.glob(str(base / "chromium_headless_shell-*" / "*" / "chrome-headless-shell")), reverse=True)
        cand += sorted(glob.glob(str(base / "chromium_headless_shell-*" / "*" / "headless_shell")), reverse=True)
    for base in bases:   # varredura por qualquer binário headless antes de cair no Chrome completo
        if base.exists():
            cand += sorted(str(p) for p in base.rglob("*headless*shell*") if p.is_file() and os.access(p, os.X_OK))
    for base in bases:
        cand += sorted(glob.glob(str(base / "chromium-*" / "chrome-linux*" / "chrome")), reverse=True)
    cand += [shutil.which("chromium") or "", shutil.which("chromium-browser") or "", shutil.which("google-chrome") or ""]
    for c in cand:
        if c and Path(c).exists():
            return c
    raise RuntimeError("Chromium não encontrado (defina AGENCIA_CHROMIUM no .env ou instale: pip install playwright && playwright install chromium)")


def _e_headless_shell(chromium: str) -> bool:
    return "headless" in Path(chromium).name


def _screenshot(chromium: str, html_path: Path, png: Path, w: int, h: int) -> None:
    cmd = [chromium] + ([] if _e_headless_shell(chromium) else ["--headless=new"]) + [
           "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--force-device-scale-factor=1",
           "--disable-dev-shm-usage", "--no-first-run", "--disable-extensions", f"--window-size={w},{h}",
           "--virtual-time-budget=1500", f"--screenshot={png}", html_path.as_uri()]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not png.exists():
        raise RuntimeError(f"chromium falhou ({r.returncode}): {r.stderr[-600:]}")


def dimensoes_png(p: Path) -> tuple[int, int]:
    b = p.read_bytes()[:24]
    return int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")


def verificar_viewport(chromium: str, w: int = 1080, h: int = 1350) -> None:
    """Falha cedo se o viewport do motor não bater com --window-size (Chrome --headless=new perde ~87px)."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "vp.html"
        p.write_text("<!doctype html><body><script>document.body.textContent=innerWidth+'x'+innerHeight</script></body>", encoding="utf-8")
        cmd = [chromium] + ([] if _e_headless_shell(chromium) else ["--headless=new"]) + [
               "--disable-gpu", "--no-sandbox", "--hide-scrollbars", f"--window-size={w},{h}", "--dump-dom", p.as_uri()]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        m = re.search(r"(\d+)x(\d+)", r.stdout)
        if not m or (int(m.group(1)), int(m.group(2))) != (w, h):
            raise RuntimeError(f"viewport de {chromium} = {m.group(0) if m else '?'} para janela {w}x{h}; use o "
                               "chromium_headless_shell do Playwright (AGENCIA_CHROMIUM=<caminho do chrome-headless-shell>) "
                               "ou instale: pip install playwright && playwright install chromium")


def renderizar(pasta: Path, raiz: Path = RAIZ, chromium: str | None = None) -> list[Path]:
    arte = yaml.safe_load((pasta / "arte.yaml").read_text(encoding="utf-8"))
    validar(arte)
    paleta = carregar_paleta(raiz)
    env = Environment(loader=FileSystemLoader(str(raiz / "templates" / "arte")), autoescape=select_autoescape(["html"]))
    base_css_tpl = env.get_template("base.css")
    tpl = env.get_template(f"{arte['template']}.html")
    logo_uri = _logo_uri(raiz, paleta)
    chromium = chromium or encontrar_chromium()
    verificar_viewport(chromium)
    for antigo in pasta.glob("arte*.png"):
        antigo.unlink()
    saidas = []
    log = logger("render", raiz)
    with tempfile.TemporaryDirectory() as tmp:
        for fmt in arte["formatos"]:
            w, h = (int(x) for x in fmt.split("x"))
            base_css = base_css_tpl.render(w=w, h=h)
            total = len(arte["slides"])
            for n, s in enumerate(arte["slides"], 1):
                page = tpl.render(p=paleta, s=s, n=n, total=total, capa=(arte["template"] == "carrossel" and n == 1),
                                  ultimo=(n == total), assinatura=arte["assinatura"], logo_uri=logo_uri,
                                  corpo_html=_corpo_html(s["corpo"], s.get("destaque")), base_css=base_css)
                html_path = Path(tmp) / f"{fmt}_{n:02d}.html"
                html_path.write_text(page, encoding="utf-8")
                sufixo = "" if len(arte["formatos"]) == 1 else f"_{fmt}"
                png = pasta / f"arte_{n:02d}{sufixo}.png"
                _screenshot(chromium, html_path, png, w, h)
                dw, dh = dimensoes_png(png)
                if (dw, dh) != (w, h):
                    raise RuntimeError(f"{png.name}: {dw}x{dh} em vez de {w}x{h}")
                saidas.append(png)
                log.info("%s %s %dx%d", pasta.name, png.name, dw, dh)
    (pasta / "alt_text.txt").write_text(arte["alt_text"].strip() + "\n", encoding="utf-8")
    return saidas


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--peca", required=True)
    ap.add_argument("--validar", action="store_true")
    ap.add_argument("--raiz", default=str(RAIZ))
    a = ap.parse_args(argv)
    raiz = Path(a.raiz)
    pasta = raiz / "conteudo" / a.peca
    try:
        if a.validar:
            validar(yaml.safe_load((pasta / "arte.yaml").read_text(encoding="utf-8")))
            print("ok: arte.yaml válido")
            return 0
        pngs = renderizar(pasta, raiz)
        print("ok: " + ", ".join(p.name for p in pngs))
        return 0
    except ArteInvalida as exc:
        print(f"ERRO arte.yaml: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
