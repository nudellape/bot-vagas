"""Fonte: Agrobase (agrobase.com.br) — estágios e bolsas do agro.

O site é WordPress; o bot lê o feed RSS padrão:
    https://www.agrobase.com.br/estagios/feed/        (estágios)
    https://www.agrobase.com.br/oportunidades/feed/   (empregos e bolsas; só entram estágios/bolsas)
O título traz a cidade: "Estágio em X – Jaguariúna/SP".
A Agrobase não informa se a vaga ainda está aberta (ela remove o botão de
candidatura depois de ~3 semanas), então essas vagas entram como NÃO CONFIRMADAS
e só se publicadas nos últimos `dias_max` dias.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime

import requests
from defusedxml import ElementTree as ET

from ..models import Vaga
from ..text import norm, strip_html

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (bot pessoal de busca de estágio)",
           "Accept": "application/rss+xml, application/xml, text/xml"}
FEEDS = [
    ("https://www.agrobase.com.br/estagios/feed/", False),
    ("https://www.agrobase.com.br/oportunidades/feed/", True),  # True = filtrar só estágio/bolsa
]
PALAVRAS_ESTAGIO = re.compile(r"estagi|intern|trainee|assistente|auxiliar|analista", re.I)
BOLSA = re.compile(r"bolsa|iniciacao cientifica|pos-?doutorado|mestrado|doutorado|treinamento tecnico", re.I)


def cidade_do_titulo(titulo: str) -> tuple[str, str]:
    """'Estágio em X – Jaguariúna/SP' -> ('Jaguariúna', 'SP')."""
    m = re.search(r"[–—-]\s*([^–—\-/]+)/([A-Z]{2})\s*$", titulo.strip())
    if m:
        return m.group(1).strip(), m.group(2)
    return "", ""


def ler_feed(xml: bytes, so_estagio: bool, alvo: set[str], hoje: date, dias_max: int) -> list[Vaga]:
    raiz = ET.fromstring(xml)
    out = []
    for item in raiz.iter("item"):
        titulo = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if BOLSA.search(norm(titulo)):
            continue  # bolsas ficam de fora: foco em trabalho
        if so_estagio and not PALAVRAS_ESTAGIO.search(norm(titulo)):
            continue
        cidade, uf = cidade_do_titulo(titulo)
        remoto = "remot" in norm(titulo)
        if norm(cidade) not in alvo and not remoto:
            continue
        try:
            pub = parsedate_to_datetime(item.findtext("pubDate") or "").date()
        except (TypeError, ValueError):
            pub = None
        if pub and (hoje - pub).days > dias_max:
            continue
        guid = item.findtext("guid") or link
        pid = re.search(r"[?&]p=(\d+)", guid)
        desc = strip_html(item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
                          or item.findtext("description") or "")
        nome = re.sub(r"\s*[–—-]\s*[^–—\-/]+/[A-Z]{2}\s*$", "", titulo)
        empresa = ""
        m = re.search(r"(?i)empresa\s*:?\s*([^\n|]{2,60})", desc)
        if m:
            empresa = m.group(1).strip()
        out.append(Vaga(
            id=f"agrobase:{pid.group(1) if pid else abs(hash(guid))}", fonte="agrobase",
            empresa=empresa or "(ver anúncio)", titulo=nome, cidade=cidade or ("remoto" if remoto else ""),
            estado=uf, modalidade="remoto" if remoto else "", descricao=desc,
            publicada_em=pub.isoformat() if pub else "", link=link, tipo="internship" if re.search(r"estagi|intern", norm(titulo)) else "",
            verificacao=f"NÃO CONFIRMADA: anúncio Agrobase de {pub.strftime('%d/%m/%Y') if pub else 'data ?'}"))
    return out


def coletar(cfg: dict, session: requests.Session | None = None):
    """Retorna (vagas, avisos, prefixos ok, ids abertos). Feed mostra só os recentes,
    então esta fonte nunca marca vagas como encerradas (prefixos ok vazio)."""
    if not (cfg.get("agrobase") or {}).get("ativo", True):
        return [], [], set(), set()
    s = session or requests.Session()
    loc = cfg["localizacao"]
    alvo = {norm(c) for c in loc["prioridade_1"] + loc["prioridade_2"]}
    dias_max = (cfg.get("agrobase") or {}).get("dias_max", 21)
    hoje = date.today()
    out, avisos = [], []
    for url, so_estagio in FEEDS:
        for pagina in (1, 2, 3):
            try:
                r = s.get(url, params={"paged": pagina} if pagina > 1 else None, headers=HEADERS, timeout=30)
                if getattr(r, "status_code", 200) == 404 and pagina > 1:
                    break
                r.raise_for_status()
                novas = ler_feed(r.content, so_estagio, alvo, hoje, dias_max)
                out += novas
            except Exception as e:  # noqa: BLE001
                avisos.append(f"agrobase {url} p{pagina}: {e}")
                break
    log.info("agrobase: %d anúncios na região", len(out))
    return out, avisos, set(), set()
