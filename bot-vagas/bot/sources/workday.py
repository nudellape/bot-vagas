"""Fonte: páginas de carreira em Workday (myworkdayjobs.com).

Endpoint JSON usado pela própria página de vagas:
    POST https://{host}/wday/cxs/{tenant}/{site}/jobs      (lista)
    GET  https://{host}/wday/cxs/{tenant}/{site}{path}     (detalhe)
Cada empresa precisa ser cadastrada em config.yaml (host/tenant/site).
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta

import requests

from ..models import Vaga
from ..text import strip_html

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (bot pessoal de busca de estágio)",
           "Accept": "application/json", "Content-Type": "application/json"}


def _data_relativa(posted_on: str, hoje: date) -> str:
    """'Posted 3 Days Ago' / 'Publicado há 3 dias' -> AAAA-MM-DD. Vazio se impreciso ('30+')."""
    p = (posted_on or "").lower()
    if "today" in p or "hoje" in p:
        return hoje.isoformat()
    if "yesterday" in p or "ontem" in p:
        return (hoje - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+?", p)
    if m and "+" not in p:
        return (hoje - timedelta(days=int(m.group(1)))).isoformat()
    return ""


def coletar_empresa(emp: dict, *, pausa: float = 1.0, session: requests.Session | None = None,
                    hoje: date | None = None) -> list[Vaga]:
    s = session or requests.Session()
    hoje = hoje or date.today()
    base = f"https://{emp['host']}/wday/cxs/{emp['tenant']}/{emp['site']}"
    vistos: dict[str, Vaga] = {}
    for termo in emp.get("termos", ["estágio", "intern"]):
        offset = 0
        while offset < 200:
            r = s.post(f"{base}/jobs", json={"appliedFacets": {}, "limit": 20, "offset": offset,
                                             "searchText": termo}, headers=HEADERS, timeout=30)
            r.raise_for_status()
            posts = r.json().get("jobPostings") or []
            for p in posts:
                path = p.get("externalPath") or ""
                if not path or path in vistos:
                    continue
                v = Vaga(id=f"workday:{emp['tenant']}:{path.rsplit('_', 1)[-1]}", fonte="workday",
                         empresa=emp["empresa"], titulo=p.get("title", ""),
                         cidade=p.get("locationsText", ""),
                         publicada_em=_data_relativa(p.get("postedOn", ""), hoje),
                         link=f"https://{emp['host']}/{emp['site']}{path}")
                try:  # detalhe: descrição, local e modalidade
                    d = s.get(f"{base}{path}", headers=HEADERS, timeout=30).json().get("jobPostingInfo", {})
                    v.descricao = strip_html(d.get("jobDescription"))
                    v.cidade = d.get("location") or v.cidade
                    v.link = d.get("externalUrl") or v.link
                    rt = (d.get("remoteType") or "").lower()
                    v.modalidade = "remoto" if "remote" in rt else "híbrido" if "hybrid" in rt else ""
                except Exception as e:  # noqa: BLE001
                    log.warning("detalhe workday %s: %s", path, e)
                vistos[path] = v
                time.sleep(pausa)
            if len(posts) < 20:
                break
            offset += 20
    return list(vistos.values())


def coletar(cfg: dict, session: requests.Session | None = None) -> tuple[list[Vaga], list[str], set[str]]:
    """Retorna (vagas, erros, prefixos de id consultados com sucesso)."""
    out, erros, ok = [], [], set()
    for emp in cfg.get("workday") or []:
        try:
            out.extend(coletar_empresa(emp, pausa=cfg["busca"].get("pausa_entre_requisicoes_seg", 1.0),
                                       session=session))
            ok.add(f"workday:{emp['tenant']}:")
        except Exception as e:  # noqa: BLE001
            erros.append(f"workday {emp.get('empresa')}: {e}")
    return out, erros, ok
