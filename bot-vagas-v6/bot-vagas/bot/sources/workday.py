"""Fonte: páginas de carreira em Workday (myworkdayjobs.com) — ex.: 3M, GE Vernova.

Endpoint JSON usado pela própria página de vagas:
    POST https://{host}/wday/cxs/{tenant}/{site}/jobs      (lista)
    GET  https://{host}/wday/cxs/{tenant}/{site}{path}     (detalhe)
Cada empresa é cadastrada em config.yaml (host/tenant/site). Endereços marcados
como "a confirmar" são testados a cada execução; se falharem, só aparece no log.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta

import requests

from ..models import Vaga
from ..text import norm, strip_html

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


def _promissora(texto_local: str, alvo: set[str]) -> bool:
    """Evita baixar detalhes de vagas claramente fora do Brasil."""
    t = norm(texto_local)
    return (not t or "brazil" in t or "brasil" in t or "locations" in t or "locais" in t
            or "remote" in t or "remoto" in t or any(c in t for c in alvo))


def coletar_empresa(emp: dict, alvo: set[str], *, pausa: float = 1.0, session: requests.Session | None = None,
                    hoje: date | None = None) -> tuple[list[Vaga], set[str]]:
    s = session or requests.Session()
    hoje = hoje or date.today()
    base = f"https://{emp['host']}/wday/cxs/{emp['tenant']}/{emp['site']}"
    vistos: dict[str, Vaga] = {}
    ids_abertos: set[str] = set()
    for termo in emp.get("termos", ["estágio", "intern"]):
        offset = 0
        while offset < 300:
            r = s.post(f"{base}/jobs", json={"appliedFacets": {}, "limit": 20, "offset": offset,
                                             "searchText": termo}, headers=HEADERS, timeout=30)
            r.raise_for_status()
            posts = r.json().get("jobPostings") or []
            for p in posts:
                path = p.get("externalPath") or ""
                if not path or path in vistos:
                    continue
                vid = f"workday:{emp['tenant']}:{path.rsplit('_', 1)[-1]}"
                ids_abertos.add(vid)
                if not _promissora(p.get("locationsText", ""), alvo):
                    continue
                v = Vaga(id=vid, fonte="workday", empresa=emp["empresa"], titulo=p.get("title", ""),
                         cidade=(p.get("locationsText") or "").split(",")[0],
                         publicada_em=_data_relativa(p.get("postedOn", ""), hoje),
                         link=f"https://{emp['host']}/{emp['site']}{path}")
                try:  # detalhe: descrição, local e modalidade
                    d = s.get(f"{base}{path}", headers=HEADERS, timeout=30).json().get("jobPostingInfo", {})
                    v.descricao = strip_html(d.get("jobDescription"))
                    v.cidade = (d.get("location") or v.cidade).split(",")[0]
                    v.link = d.get("externalUrl") or v.link
                    rt = norm(d.get("remoteType") or "")
                    v.modalidade = "remoto" if "remote" in rt else "híbrido" if "hybrid" in rt else ""
                except Exception as e:  # noqa: BLE001
                    log.info("detalhe workday %s: %s", path, e)
                vistos[path] = v
                time.sleep(pausa)
            if len(posts) < 20:
                break
            offset += 20
    log.info("workday %s: %d vagas analisadas", emp["empresa"], len(vistos))
    return list(vistos.values()), ids_abertos


def coletar(cfg: dict, session: requests.Session | None = None):
    """Retorna (vagas, avisos, prefixos ok, ids abertos). Falhas aqui não geram alerta."""
    loc = cfg["localizacao"]
    alvo = {norm(c) for c in loc["prioridade_1"] + loc["prioridade_2"]}
    out, avisos, ok, ids = [], [], set(), set()
    for emp in cfg.get("workday") or []:
        try:
            v, i = coletar_empresa(emp, alvo, pausa=cfg["busca"].get("pausa_entre_requisicoes_seg", 1.0),
                                   session=session)
            out += v
            ids |= i
            ok.add(f"workday:{emp['tenant']}:")
        except Exception as e:  # noqa: BLE001
            avisos.append(f"workday {emp.get('empresa')}: {e}")
            log.warning("falha workday %s (endereço pode estar errado): %s", emp.get("empresa"), e)
    return out, avisos, ok, ids
