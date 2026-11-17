"""Fonte: portal público de vagas da Gupy (portal.gupy.io).

Usa o endpoint interno que alimenta o próprio portal (não documentado; pode mudar):
    GET https://portal.gupy.io/api/job-search/jobs?jobName=...&limit=..&offset=..
O endereço antigo (portal.api.gupy.io / employability-portal.gupy.io) passou a
responder 404 em out/2026; fica como reserva caso volte.
"""
from __future__ import annotations

import logging
import time

import requests

from ..models import Vaga
from ..text import norm, strip_html

log = logging.getLogger(__name__)

ENDPOINTS = [
    "https://portal.gupy.io/api/job-search/jobs",
    "https://employability-portal.gupy.io/api/v1/jobs",
    "https://portal.api.gupy.io/api/v1/jobs",
]
_endpoint_ok: str | None = None
PAGE = 10
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Origin": "https://portal.gupy.io",
    "Referer": "https://portal.gupy.io/",
}

MODALIDADE = {"remote": "remoto", "hybrid": "híbrido", "on-site": "presencial", "onsite": "presencial"}


def _to_vaga(j: dict) -> Vaga:
    modalidade = MODALIDADE.get((j.get("workplaceType") or "").lower(), "")
    if not modalidade and j.get("isRemoteWork") is True:
        modalidade = "remoto"
    return Vaga(
        id=f"gupy:{j.get('id')}",
        fonte="gupy",
        empresa=(j.get("careerPageName") or "").strip(),
        titulo=(j.get("name") or "").strip(),
        cidade=(j.get("city") or "").strip(),
        estado=(j.get("state") or "").strip(),
        modalidade=modalidade,
        descricao=strip_html(j.get("description")),
        publicada_em=(j.get("publishedDate") or "")[:10],
        prazo=(j.get("applicationDeadline") or "")[:10],
        link=j.get("jobUrl") or "",
        tipo=j.get("type") or "",
    )


def _paginar(url: str, job_name: str, city: str | None, max_paginas: int, pausa: float,
             s: requests.Session) -> list[Vaga]:
    vagas: list[Vaga] = []
    for pagina in range(max_paginas):
        params = {"jobName": job_name, "limit": PAGE, "offset": pagina * PAGE}
        if city:
            params["city"] = city
        r = s.get(url, params=params, headers=HEADERS, timeout=30)
        if getattr(r, "status_code", 200) >= 400:
            corpo = (getattr(r, "text", "") or "")[:200].replace("\n", " ")
            raise requests.HTTPError(f"{r.status_code} em {getattr(r, 'url', url)} | resposta: {corpo}")
        payload = r.json()
        dados = payload.get("data") or []
        vagas.extend(_to_vaga(j) for j in dados)
        total = (payload.get("pagination") or {}).get("total")
        if not dados or len(dados) < PAGE or (total is not None and (pagina + 1) * PAGE >= total):
            break
        time.sleep(pausa)
    return vagas


def buscar(job_name: str, *, city: str | None = None, max_paginas: int = 15, pausa: float = 1.0,
           session: requests.Session | None = None) -> list[Vaga]:
    s = session or requests.Session()
    sem_acento = norm(job_name)
    tentativas = [(job_name, city)]
    if sem_acento != job_name.lower():
        tentativas.append((sem_acento, city))
    if city:
        tentativas.append((sem_acento, None))
    global _endpoint_ok
    urls = [_endpoint_ok] if _endpoint_ok else ENDPOINTS
    ultimo_erro: Exception | None = None
    for url in urls:
        for termo, cid in tentativas:
            try:
                vagas = _paginar(url, termo, cid, max_paginas, pausa, s)
                _endpoint_ok = url
                log.info("gupy %s jobName=%r city=%r -> %d", url, termo, cid, len(vagas))
                return vagas
            except Exception as e:  # noqa: BLE001
                ultimo_erro = e
                log.info("tentativa falhou (%s jobName=%r city=%r): %s", url, termo, cid, e)
                time.sleep(pausa)
    raise ultimo_erro  # type: ignore[misc]


def coletar(cfg: dict, session: requests.Session | None = None) -> tuple[list[Vaga], list[str]]:
    b = cfg["busca"]
    loc = cfg["localizacao"]
    pausa = b.get("pausa_entre_requisicoes_seg", 1.0)
    maxp = b.get("max_paginas", 15)
    s = session or requests.Session()
    out: list[Vaga] = []
    erros: list[str] = []

    consultas = ([(t, c) for c in loc["prioridade_1"] + loc["prioridade_2"] for t in b["gupy_termos_por_cidade"]]
                 + [(t, None) for t in b["gupy_termos_remotos"]])
    for termo, cidade in consultas:
        try:
            out.extend(buscar(termo, city=cidade, max_paginas=maxp, pausa=pausa, session=s))
        except Exception as e:  # noqa: BLE001
            erros.append(f"gupy '{termo}' {cidade or 'nacional'}: {e}")
            log.warning("falha gupy %s %s: %s", termo, cidade or "nacional", e)
        time.sleep(pausa)
    return out, erros
