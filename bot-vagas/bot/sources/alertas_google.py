"""Fonte: Google Alertas entregues como feed RSS (Atom).

Como configurar (uma vez): em google.com/alerts, crie um alerta para cada busca
(ex.: "programa de estágio" 2027 Campinas), em "Mostrar opções" escolha
"Entregar para: Feed RSS", e copie o endereço do feed (ícone RSS) para
config.yaml -> alertas_google.

O bot lê os feeds todo dia, fica com resultados que falam de estágio/programa,
descobre a cidade pelo texto e registra como NÃO CONFIRMADA (é uma página ou
notícia encontrada na web: abra e confira prazo e requisitos).
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date
from urllib.parse import parse_qs, urlparse

import requests
from defusedxml import ElementTree as ET

from ..models import Vaga
from ..text import norm, strip_html
from .fapesp import prazo_do_texto

log = logging.getLogger(__name__)
ATOM = "{http://www.w3.org/2005/Atom}"
HEADERS = {"User-Agent": "Mozilla/5.0 (bot pessoal de busca de estágio)"}
RELEVANTE = re.compile(r"estagi|internship|trainee|programa de talentos|jovens talentos")
IGNORAR = re.compile(r"jovem aprendiz|ensino medio|curso tecnico|estagio tecnico|nivel tecnico|"
                     r"pos-?doutorado|mestrado|doutorado|bolsa de iniciacao")


def url_real(link: str) -> str:
    """Links do Google Alertas vêm como https://www.google.com/url?...&url=REAL&..."""
    q = parse_qs(urlparse(link).query)
    return q.get("url", [link])[0]


def ler_feed(xml: bytes, cidades: list[str], cidade_padrao: str, hoje: date) -> list[Vaga]:
    raiz = ET.fromstring(xml)
    out = []
    for e in raiz.iter(f"{ATOM}entry"):
        titulo = strip_html(e.findtext(f"{ATOM}title") or "")
        resumo = strip_html(e.findtext(f"{ATOM}content") or "")
        lk = e.find(f"{ATOM}link")
        link = url_real(lk.get("href", "")) if lk is not None else ""
        texto_n = norm(f"{titulo} {resumo}")
        if not link or not RELEVANTE.search(texto_n) or IGNORAR.search(texto_n):
            continue
        cidade = next((c for c in cidades if re.search(rf"(?<![a-z]){re.escape(norm(c))}(?![a-z])", texto_n)), "")
        cidade = cidade or cidade_padrao
        pub = (e.findtext(f"{ATOM}published") or e.findtext(f"{ATOM}updated") or "")[:10]
        prazo = prazo_do_texto(texto_n, pub)
        if prazo and prazo < hoje.isoformat():
            continue
        dominio = urlparse(link).netloc.replace("www.", "")
        out.append(Vaga(
            id="alerta:" + hashlib.sha1(link.encode()).hexdigest()[:12], fonte="google_alertas",
            empresa=dominio, titulo=titulo[:200], cidade=cidade, descricao=resumo, publicada_em=pub,
            prazo=prazo, link=link, tipo="internship",
            verificacao=f"NÃO CONFIRMADA: encontrado pelo Google Alertas ({dominio}); abra e confira"))
    return out


def coletar(cfg: dict, session: requests.Session | None = None):
    feeds = cfg.get("alertas_google") or []
    if not feeds:
        return [], [], set(), set()
    s = session or requests.Session()
    loc = cfg["localizacao"]
    cidades = loc["prioridade_1"] + loc["prioridade_2"] + ["Barão Geraldo"]
    hoje = date.today()
    out, avisos, vistos = [], [], set()
    for f in feeds:
        url = f["feed"] if isinstance(f, dict) else f
        padrao = (f.get("cidade") if isinstance(f, dict) else "") or ""
        try:
            r = s.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            for v in ler_feed(r.content, cidades, padrao, hoje):
                if v.link not in vistos:
                    vistos.add(v.link)
                    if v.cidade == "Barão Geraldo":
                        v.cidade = "Campinas"
                    out.append(v)
        except Exception as e:  # noqa: BLE001
            avisos.append(f"google alertas {url[:60]}: {e}")
    log.info("google alertas: %d resultados relevantes", len(out))
    return out, avisos, set(), set()
