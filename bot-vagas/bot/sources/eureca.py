"""Fonte: Eureca (app.eureca.me), plataforma de programas de estágio de empresas grandes.

API pública usada pelo próprio site (responde sem login):
    GET https://candidate-api.eureca.me/opportunities   -> {items, total, page, pageSize}
Cada item traz empresa, programa, modelo de trabalho, cidades, horas por semana e fim das inscrições.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import requests

from ..models import Vaga
from ..text import norm, strip_html

log = logging.getLogger(__name__)
URL = "https://candidate-api.eureca.me/opportunities"
HEADERS = {"User-Agent": "Mozilla/5.0 (bot pessoal de busca de estágio)", "Accept": "application/json",
           "Origin": "https://app.eureca.me", "Referer": "https://app.eureca.me/"}
MODELO = {"remoto": "remoto", "hibrido": "híbrido", "presencial": "presencial"}


def _prazo(fim: str | None) -> str:
    """endApplying vem em UTC; 02:59 UTC é 23:59 do dia anterior em Brasília."""
    if not fim:
        return ""
    try:
        d = datetime.fromisoformat(fim.replace("Z", "+00:00")) - timedelta(hours=3)
        return d.date().isoformat()
    except ValueError:
        return fim[:10]


def _modalidade(it: dict) -> str:
    modelos = [m for m in (it.get("workModels") or [it.get("workModel")]) if m]
    if "remoto" in modelos:
        return "remoto"
    if "hibrido" in modelos:
        return "híbrido"
    return MODELO.get(modelos[0], "") if modelos else ""


def _cidade(it: dict, alvo: set[str]) -> tuple[str, str]:
    loc = it.get("locations") or {}
    cidades = loc.get("cities") or ([it["cityName"]] if it.get("cityName") else [])
    estados = loc.get("states") or ([it["stateAcronym"]] if it.get("stateAcronym") else [])
    for c in cidades:  # prefer a city in Nu's list when the job has several
        if norm(c) in alvo:
            return c, (estados[0] if estados else "")
    return (cidades[0] if cidades else ""), (estados[0] if estados else "")


def vagas_dos_itens(itens: list[dict], alvo: set[str]) -> list[Vaga]:
    out = []
    for it in itens:
        if it.get("contractTypeKey") != "internship":
            continue
        cidade, estado = _cidade(it, alvo)
        horas = it.get("weeklyHours")
        desc = strip_html(it.get("description") or "")
        if horas:
            desc = f"Carga horária: {horas} horas semanais.\n{desc}"
        programa = it.get("programName") or ""
        titulo = it.get("name", "")
        if programa and norm(programa) not in norm(titulo):
            titulo = f"{titulo} ({programa})"
        out.append(Vaga(id=f"eureca:{it['id']}", fonte="eureca", empresa=it.get("companyName", ""),
                        titulo=titulo, cidade=cidade, estado=estado, modalidade=_modalidade(it),
                        descricao=desc, publicada_em=(it.get("publishedAt") or it.get("createdAt") or "")[:10],
                        prazo=_prazo(it.get("endApplying")), link=f"https://app.eureca.me/vagas/{it['id']}",
                        tipo="internship"))
    return out


def coletar(cfg: dict, session: requests.Session | None = None):
    """Retorna (vagas, avisos, prefixos ok, ids abertos)."""
    if not (cfg.get("eureca") or {}).get("ativo", True):
        return [], [], set(), set()
    s = session or requests.Session()
    loc = cfg["localizacao"]
    alvo = {norm(c) for c in loc["prioridade_1"] + loc["prioridade_2"]}
    itens, pagina = [], 1
    try:
        while pagina <= 20:
            r = s.get(URL, params={"page": pagina, "pageSize": 200}, headers=HEADERS, timeout=30)
            r.raise_for_status()
            d = r.json()
            lote = d.get("items") or []
            itens += lote
            if not lote or len(itens) >= (d.get("total") or 0):
                break
            pagina += 1
    except Exception as e:  # noqa: BLE001
        log.warning("falha eureca: %s", e)
        return [], [f"eureca: {e}"], set(), set()
    vagas = vagas_dos_itens(itens, alvo)
    log.info("eureca: %d oportunidades, %d estágios", len(itens), len(vagas))
    return vagas, [], {"eureca:"}, {f"eureca:{it['id']}" for it in itens}
