"""Fonte: SmartRecruiters (ex.: Bosch Brasil — careers.smartrecruiters.com/BoschGroup).

API pública de anúncios (sem login):
    GET https://api.smartrecruiters.com/v1/companies/{empresa}/postings?country=br&q=..&limit=100&offset=..
    GET https://api.smartrecruiters.com/v1/companies/{empresa}/postings/{id}   (detalhe)
"""
from __future__ import annotations

import logging
import time

import requests

from ..models import Vaga
from ..text import norm, strip_html

log = logging.getLogger(__name__)
BASE = "https://api.smartrecruiters.com/v1/companies"
HEADERS = {"User-Agent": "Mozilla/5.0 (bot pessoal de busca de estágio)", "Accept": "application/json"}


def _modalidade(loc: dict) -> str:
    if loc.get("remote"):
        return "remoto"
    if loc.get("hybrid"):
        return "híbrido"
    return ""


def _eh_estagio(p: dict) -> bool:
    nivel = norm((p.get("experienceLevel") or {}).get("id", "") + " " + (p.get("experienceLevel") or {}).get("label", ""))
    tipo = norm((p.get("typeOfEmployment") or {}).get("label", ""))
    titulo = norm(p.get("name", ""))
    return "intern" in nivel or "estagi" in tipo or "intern" in tipo or "estagi" in titulo or "intern" in titulo


def coletar_empresa(emp: dict, cidades_alvo: set[str], *, pausa: float = 1.0,
                    session: requests.Session | None = None) -> tuple[list[Vaga], set[str]]:
    s = session or requests.Session()
    ident = emp["id"]
    vistos: dict[str, dict] = {}
    for termo in emp.get("termos", [""]):
        offset = 0
        while offset < 1000:
            params = {"country": emp.get("pais", "br"), "limit": 100, "offset": offset}
            if termo:
                params["q"] = termo
            r = s.get(f"{BASE}/{ident}/postings", params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            d = r.json()
            itens = d.get("content") or []
            for p in itens:
                vistos.setdefault(str(p.get("id")), p)
            offset += len(itens)
            if not itens or offset >= (d.get("totalFound") or 0):
                break
            time.sleep(pausa)
    ids_abertos = {f"sr:{ident}:{i}" for i in vistos}

    out: list[Vaga] = []
    for pid, p in vistos.items():
        loc = p.get("location") or {}
        cidade = (loc.get("city") or "").strip()
        if not _eh_estagio(p):
            continue
        if norm(cidade) not in cidades_alvo and not loc.get("remote"):
            continue
        v = Vaga(id=f"sr:{ident}:{pid}", fonte="smartrecruiters",
                 empresa=emp.get("empresa") or (p.get("company") or {}).get("name", ident),
                 titulo=p.get("name", ""), cidade=cidade, estado=loc.get("region", ""),
                 modalidade=_modalidade(loc), publicada_em=(p.get("releasedDate") or "")[:10],
                 link=f"https://jobs.smartrecruiters.com/{ident}/{pid}", tipo="internship")
        try:  # descrição completa (para curso, jornada, bolsa)
            det = s.get(f"{BASE}/{ident}/postings/{pid}", headers=HEADERS, timeout=30).json()
            secoes = ((det.get("jobAd") or {}).get("sections") or {})
            v.descricao = "\n".join(strip_html((secoes.get(k) or {}).get("text"))
                                    for k in ("jobDescription", "qualifications", "additionalInformation"))
            v.link = det.get("postingUrl") or det.get("applyUrl") or v.link
        except Exception as e:  # noqa: BLE001
            log.info("detalhe smartrecruiters %s: %s", pid, e)
        out.append(v)
        time.sleep(pausa)
    log.info("smartrecruiters %s: %d anúncios no país, %d estágios na região", ident, len(vistos), len(out))
    return out, ids_abertos


def coletar(cfg: dict, session: requests.Session | None = None):
    """Retorna (vagas, avisos, prefixos ok, ids abertos)."""
    loc = cfg["localizacao"]
    alvo = {norm(c) for c in loc["prioridade_1"] + loc["prioridade_2"]}
    out, avisos, ok, ids = [], [], set(), set()
    for emp in cfg.get("smartrecruiters") or []:
        try:
            v, i = coletar_empresa(emp, alvo, pausa=cfg["busca"].get("pausa_entre_requisicoes_seg", 1.0),
                                   session=session)
            out += v
            ids |= i
            ok.add(f"sr:{emp['id']}:")
        except Exception as e:  # noqa: BLE001
            avisos.append(f"smartrecruiters {emp.get('empresa', emp.get('id'))}: {e}")
            log.warning("falha smartrecruiters %s: %s", emp.get("id"), e)
    return out, avisos, ok, ids
