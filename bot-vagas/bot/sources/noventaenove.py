"""Fonte: 99jobs (99jobs.com), programas de estágio de empresas grandes.

A busca é pública (sem login) e vem pronta no HTML:
    GET https://99jobs.com/opportunities/filtered_search?search[term]=estagio&page=N   (25 por página)
Cada cartão (a.opportunity-card) traz título, nível, modelo de trabalho, cidade e empresa.
A página da vaga também é pública; dela vem o título completo e a descrição.
"""
from __future__ import annotations

import logging
import time

import requests
from bs4 import BeautifulSoup

from ..models import Vaga
from ..text import norm

log = logging.getLogger(__name__)
BASE = "https://99jobs.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (bot pessoal de busca de estágio)"}
MODELO = {"remoto": "remoto", "home office": "remoto", "hibrido": "híbrido", "presencial": "presencial"}


def _txt(el) -> str:
    return " ".join(el.get_text(" ").split()) if el else ""


def cartoes(html: str) -> list[dict]:
    out = []
    for a in BeautifulSoup(html, "html.parser").select("a.opportunity-card"):
        href = (a.get("href") or "").split("?")[0]
        if not href:
            continue
        if href.startswith("/"):
            href = BASE + href
        endereco = _txt(a.select_one(".opportunity-address")).strip(" ,")
        if norm(endereco) in {"nao informado", "nao informada"}:
            endereco = ""
        partes = [p.strip() for p in endereco.split(",") if p.strip()]
        out.append({
            "link": href, "id": href.rstrip("/").split("/")[-1].split("-")[0],
            "titulo": _txt(a.select_one("h1")).rstrip(". "),
            "nivel": _txt(a.select_one(".opportunity-label-level")),
            "modelo": _txt(a.select_one(".opportunity-label-acting-mode")),
            "cidade": partes[0] if partes else "", "estado": partes[1] if len(partes) > 1 else "",
            "empresa": _txt(a.select_one(".opportunity-company-infos h2")),
        })
    return out


def detalhe(html: str) -> tuple[str, str]:
    s = BeautifulSoup(html, "html.parser")
    box = s.select_one(".opportunities-details") or s
    titulo = next((_txt(h) for h in box.select("h2") if _txt(h)), "")
    corpo = box.select_one(".content-admin")
    desc = corpo.get_text("\n", strip=True) if corpo else ""
    return titulo, desc


def _interessa(c: dict, alvo: set[str], hibrido_ok: set[str]) -> bool:
    """Quick filter before opening each job page (the main filter runs later)."""
    if "estagi" not in norm(c["nivel"] + " " + c["titulo"]):
        return False
    cid = norm(c["cidade"])
    modelo = MODELO.get(norm(c["modelo"]), "")
    return cid in alvo or modelo == "remoto" or not cid or (cid in hibrido_ok and modelo != "presencial")


def coletar(cfg: dict, session: requests.Session | None = None):
    """Retorna (vagas, avisos, prefixos ok, ids abertos)."""
    conf = cfg.get("noventaenove") or {}
    if not conf.get("ativo", True):
        return [], [], set(), set()
    s = session or requests.Session()
    loc = cfg["localizacao"]
    alvo = {norm(c) for c in loc["prioridade_1"] + loc["prioridade_2"]}
    hib = {norm(c) for c in loc.get("hibrido_ok", [])}
    pausa = cfg["busca"].get("pausa_entre_requisicoes_seg", 1.0)
    vistos: dict[str, dict] = {}
    try:
        for termo in conf.get("termos", ["estagio"]):
            for pagina in range(1, conf.get("max_paginas", 15) + 1):
                r = s.get(f"{BASE}/opportunities/filtered_search",
                          params={"search[term]": termo, "page": pagina}, headers=HEADERS, timeout=30)
                r.raise_for_status()
                lote = cartoes(r.text)
                if not lote:
                    break
                for c in lote:
                    vistos.setdefault(c["id"], c)
                time.sleep(pausa)
    except Exception as e:  # noqa: BLE001
        log.warning("falha 99jobs: %s", e)
        return [], [f"99jobs: {e}"], set(), set()

    out = []
    for c in vistos.values():
        if not _interessa(c, alvo, hib):
            continue
        titulo, desc = c["titulo"], ""
        try:
            titulo_d, desc = detalhe(s.get(c["link"], headers=HEADERS, timeout=30).text)
            titulo = titulo_d or titulo
        except Exception as e:  # noqa: BLE001
            log.info("detalhe 99jobs %s: %s", c["id"], e)
        out.append(Vaga(id=f"99jobs:{c['id']}", fonte="99jobs", empresa=c["empresa"].title(), titulo=titulo,
                        cidade=c["cidade"], estado=c["estado"], modalidade=MODELO.get(norm(c["modelo"]), ""),
                        descricao=desc, link=c["link"], tipo="internship"))
        time.sleep(pausa)
    log.info("99jobs: %d anúncios, %d estágios para analisar", len(vistos), len(out))
    return out, [], {"99jobs:"}, {f"99jobs:{i}" for i in vistos}
