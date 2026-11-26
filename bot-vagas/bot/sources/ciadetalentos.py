"""Fonte: Cia de Talentos (vagas.ciadetalentos.com.br), programas de estágio de empresas grandes.

Lista pública usada pelo próprio site (sem login):
    POST https://vagas.ciadetalentos.com.br/applicant/rest/applicant/authentication/filter   corpo: {}
A lista inclui programas já encerrados; aberto = opportunityInscriptionEnd verdadeiro e countFinishDays >= 0
(countFinishDays = dias até o fim das inscrições).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import requests

from ..models import Vaga
from ..text import norm, strip_html

log = logging.getLogger(__name__)
URL = "https://vagas.ciadetalentos.com.br/applicant/rest/applicant/authentication/filter"
HEADERS = {"User-Agent": "Mozilla/5.0 (bot pessoal de busca de estágio)", "Accept": "application/json",
           "Content-Type": "application/json"}


def _cidade(locs) -> str:
    if isinstance(locs, list):
        locs = ", ".join(str(x) for x in locs)
    t = str(locs or "").replace("Localidade:", "").strip(" \"'")
    return "" if norm(t) in {"diversas", "diversos", ""} else t


def vagas_dos_itens(itens: list[dict], hoje: date) -> list[Vaga]:
    out = []
    for it in itens:
        tipo = norm(it.get("hiringType") or "")
        nome = it.get("opportunityName") or ""
        if any(x in tipo for x in ("tecnico", "trainee", "medio")):
            continue
        if "estagio superior" not in tipo and "estagi" not in norm(nome):
            continue
        dias = it.get("countFinishDays")
        if it.get("opportunityInscriptionEnd") is not True or not isinstance(dias, int) or dias < 0:
            continue
        out.append(Vaga(id=f"cia:{it.get('opportunityId')}", fonte="ciadetalentos",
                        empresa=it.get("companyName", ""), titulo=nome, cidade=_cidade(it.get("opportunityLocations")),
                        descricao=strip_html(it.get("opportunityDescription") or ""),
                        prazo=(hoje + timedelta(days=dias)).isoformat(),
                        link=it.get("opportunityHotsiteUrl") or it.get("opportunityInscriptionUrl") or
                        "https://vagas.ciadetalentos.com.br/applicant/#/opportunities",
                        tipo="internship"))
    return out


def coletar(cfg: dict, session: requests.Session | None = None):
    if not (cfg.get("ciadetalentos") or {}).get("ativo", True):
        return [], [], set(), set()
    s = session or requests.Session()
    try:
        r = s.post(URL, data="{}", headers=HEADERS, timeout=30)
        r.raise_for_status()
        itens = r.json() or []
    except Exception as e:  # noqa: BLE001
        log.warning("falha cia de talentos: %s", e)
        return [], [f"cia de talentos: {e}"], set(), set()
    vagas = vagas_dos_itens(itens, date.today())
    log.info("cia de talentos: %d programas na lista, %d estágios abertos", len(itens), len(vagas))
    return vagas, [], {"cia:"}, {v.id for v in vagas}
