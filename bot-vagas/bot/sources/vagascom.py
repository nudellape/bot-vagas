"""Fonte: Vagas.com (vagas.com.br). Páginas públicas por cidade, no HTML:
    GET https://www.vagas.com.br/vagas-de-estagio-em-<cidade>     e  .../vagas-de-estagio-em-home-office
Cada li.vaga traz cargo, empresa, nível, cidade e data de publicação.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from ..models import Vaga
from ..text import norm

log = logging.getLogger(__name__)
BASE = "https://www.vagas.com.br"
HEADERS = {"User-Agent": "Mozilla/5.0 (bot pessoal de busca de estágio)"}


def slug(cidade: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", norm(cidade)).strip("-")


def _txt(el) -> str:
    return " ".join(el.get_text(" ").split()) if el else ""


def vagas_da_pagina(html: str, remoto: bool = False) -> list[Vaga]:
    out = []
    for li in BeautifulSoup(html, "html.parser").select("li.vaga"):
        a = li.select_one("a.link-detalhes-vaga")
        if not a or "estagi" not in norm(_txt(li.select_one(".nivelVaga")) + " " + _txt(a)):
            continue
        href = (a.get("href") or "").split("?")[0]
        m = re.search(r"/vagas/(v\d+)", href)
        if not m:
            continue
        local = li.select_one(".vaga-local")
        local_txt = ""
        if local:
            tip = local.select_one(".tooltip-place")
            if tip:
                tip.extract()
            local_txt = _txt(local)
        cid, _, uf = local_txt.partition("/")
        pub = _txt(li.select_one(".data-publicacao"))
        try:
            pub = datetime.strptime(pub, "%d/%m/%Y").date().isoformat()
        except ValueError:
            pub = ""
        out.append(Vaga(id=f"vagascom:{m.group(1)}", fonte="vagascom", empresa=_txt(li.select_one(".emprVaga")),
                        titulo=_txt(a), cidade=cid.strip(), estado=uf.strip(), modalidade="remoto" if remoto else "",
                        descricao=_txt(li.select_one(".detalhes")), publicada_em=pub,
                        link=BASE + href if href.startswith("/") else href, tipo="internship"))
    return out


def coletar(cfg: dict, session: requests.Session | None = None):
    if not (cfg.get("vagascom") or {}).get("ativo", True):
        return [], [], set(), set()
    s = session or requests.Session()
    loc = cfg["localizacao"]
    paginas = [(slug(c), False) for c in loc["prioridade_1"] + loc["prioridade_2"]] + [("home-office", True)]
    pausa = cfg["busca"].get("pausa_entre_requisicoes_seg", 1.0)
    vistos: dict[str, Vaga] = {}
    avisos = []
    for sl, remoto in paginas:
        try:
            r = s.get(f"{BASE}/vagas-de-estagio-em-{sl}", headers=HEADERS, timeout=30)
            r.raise_for_status()
            for v in vagas_da_pagina(r.text, remoto):
                vistos.setdefault(v.id, v)
        except Exception as e:  # noqa: BLE001
            avisos.append(f"vagas.com {sl}: {e}")
            log.warning("falha vagas.com %s: %s", sl, e)
        time.sleep(pausa)
    log.info("vagas.com: %d estágios", len(vistos))
    ok = {"vagascom:"} if not avisos else set()
    return list(vistos.values()), avisos, ok, set(vistos)
