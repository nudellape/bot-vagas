"""Vigia de páginas de carreira.

Para cada página cadastrada em config.yaml (vigia:), o bot baixa o texto, guarda só
as linhas que falam de estágio/vagas/inscrições e compara com o dia anterior.
Se aparecerem linhas novas, avisa no Telegram e mostra no site.

O estado fica numa aba "Vigia" da planilha (ou em dados/vigia.json, sem planilha).
Páginas montadas por JavaScript podem vir vazias: nesse caso o site mostra
"não consegui ler o conteúdo" e o link para abrir manualmente.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

import requests

from .text import norm, strip_html

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
           "Accept": "text/html,application/xhtml+xml", "Accept-Language": "pt-BR,pt;q=0.9"}
CHAVES = re.compile(r"estagi|estágio|internship|intern\b|trainee|programa de|inscri|vaga|processo seletivo|"
                    r"edital|30 ?h|6 ?h(oras)? ?(por dia|diarias)", re.I)
ABA = "Vigia"
COLS = ["URL", "Hash", "Linhas", "Mudou em", "Verificado em", "Situação"]


def linhas_relevantes(html: str) -> list[str]:
    html = re.sub(r"(?is)<(script|style|noscript|svg|head).*?</\1>", " ", html)
    texto = strip_html(html)
    vistas, out = set(), []
    for ln in texto.split("\n"):
        ln = re.sub(r"\s+", " ", ln).strip()
        if 6 <= len(ln) <= 220 and CHAVES.search(ln):
            chave = norm(ln)
            if chave not in vistas:
                vistas.add(chave)
                out.append(ln)
    return out[:80]


def verificar(paginas: list[dict], anterior: dict[str, dict], hoje_br: str,
              session: requests.Session | None = None) -> tuple[dict[str, dict], list[str], list[dict]]:
    """Retorna (estado novo por URL, mensagens de mudança, resumo para o site)."""
    s = session or requests.Session()
    estado, mudancas, resumo = {}, [], []
    for p in paginas:
        url, nome = p["url"], p["nome"]
        velho = anterior.get(url, {})
        item = {"nome": nome, "url": url, "cidade": p.get("cidade", ""), "obs": p.get("obs", ""),
                "mudou_em": velho.get("Mudou em", ""), "novas": [], "trechos": [], "situacao": ""}
        try:
            r = s.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            linhas = linhas_relevantes(r.text)
        except Exception as e:  # noqa: BLE001
            log.warning("vigia %s: %s", nome, e)
            item["situacao"] = "não consegui abrir a página hoje"
            item["trechos"] = json.loads(velho.get("Linhas") or "[]")[:6]
            estado[url] = {**velho, "URL": url, "Verificado em": hoje_br, "Situação": item["situacao"]}
            resumo.append(item)
            continue
        h = hashlib.sha256("\n".join(norm(x) for x in linhas).encode()).hexdigest()[:16]
        antigas = {norm(x) for x in json.loads(velho.get("Linhas") or "[]")}
        if not linhas:
            situacao = "não consegui ler o conteúdo (página montada por JavaScript): abra o link"
        elif not velho:
            situacao = "primeira leitura"
        elif h != velho.get("Hash"):
            novas = [x for x in linhas if norm(x) not in antigas]
            if novas:
                item["novas"] = novas[:8]
                item["mudou_em"] = hoje_br
                mudancas.append(f"Página de carreira mudou: {nome} — " + " | ".join(novas[:3])[:300])
            situacao = "mudou hoje" if novas else "sem novidades"
        else:
            situacao = "sem novidades"
        item["situacao"] = situacao
        item["trechos"] = linhas[:6]
        estado[url] = {"URL": url, "Hash": h, "Linhas": json.dumps(linhas, ensure_ascii=False),
                       "Mudou em": item["mudou_em"], "Verificado em": hoje_br, "Situação": situacao}
        resumo.append(item)
    return estado, mudancas, resumo


# ------------------------------------------------------------- persistência

def ler_estado(planilha=None, caminho="dados/vigia.json") -> dict[str, dict]:
    if planilha is not None:
        import gspread
        try:
            aba = planilha.worksheet(ABA)
        except gspread.WorksheetNotFound:
            return {}
        return {r["URL"]: r for r in aba.get_all_records(default_blank="") if r.get("URL")}
    p = Path(caminho)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def gravar_estado(estado: dict[str, dict], planilha=None, caminho="dados/vigia.json") -> None:
    if planilha is not None:
        import gspread
        try:
            aba = planilha.worksheet(ABA)
        except gspread.WorksheetNotFound:
            aba = planilha.add_worksheet(ABA, rows=100, cols=len(COLS))
            try:
                planilha.batch_update({"requests": [{"updateSheetProperties": {
                    "properties": {"sheetId": aba.id, "hidden": True}, "fields": "hidden"}}]})
            except Exception:  # noqa: BLE001
                pass
        valores = [COLS] + [[str(e.get(c, ""))[:45000] for c in COLS] for e in estado.values()]
        aba.clear()
        aba.update(valores, "A1", value_input_option="RAW")
        return
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
