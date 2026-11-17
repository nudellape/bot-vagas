"""Fonte: portal público de vagas da Gupy (portal.gupy.io).

Usa o endpoint público que alimenta o próprio portal:
    GET https://portal.api.gupy.io/api/v1/jobs?jobName=...&limit=..&offset=..
Não requer login. O portal lista apenas vagas com inscrições abertas, então
"aparecer na busca" é a evidência de que a vaga está aberta naquele momento.

Parâmetros opcionais como `city` e `workplaceType` reduzem o volume; se a API
os ignorar, o filtro local garante o resultado correto.
"""
from __future__ import annotations

import logging
import time
from typing import Iterable

import requests

from ..models import Vaga
from ..text import strip_html

log = logging.getLogger(__name__)

URL = "https://portal.api.gupy.io/api/v1/jobs"
PAGE = 10  # tamanho de página aceito pelo portal
HEADERS = {"User-Agent": "Mozilla/5.0 (bot pessoal de busca de estágio)", "Accept": "application/json"}

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


def buscar(job_name: str, *, city: str | None = None, workplace_type: str | None = None,
           max_paginas: int = 15, pausa: float = 1.0, session: requests.Session | None = None) -> list[Vaga]:
    """Busca paginada. Lança exceção se a primeira página falhar (para o chamador
    saber que a fonte não foi consultada e não marcar vagas como encerradas)."""
    s = session or requests.Session()
    vagas: list[Vaga] = []
    for pagina in range(max_paginas):
        params = {"jobName": job_name, "limit": PAGE, "offset": pagina * PAGE}
        if city:
            params["city"] = city
        if workplace_type:
            params["workplaceType"] = workplace_type
        r = s.get(URL, params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        payload = r.json()
        dados = payload.get("data") or []
        vagas.extend(_to_vaga(j) for j in dados)
        total = (payload.get("pagination") or {}).get("total")
        if not dados or len(dados) < PAGE or (total is not None and (pagina + 1) * PAGE >= total):
            break
        time.sleep(pausa)
    log.info("gupy jobName=%r city=%r wt=%r -> %d", job_name, city, workplace_type, len(vagas))
    return vagas


def coletar(cfg: dict, session: requests.Session | None = None) -> tuple[list[Vaga], list[str]]:
    """Executa todas as consultas configuradas. Retorna (vagas, erros)."""
    b = cfg["busca"]
    loc = cfg["localizacao"]
    pausa = b.get("pausa_entre_requisicoes_seg", 1.0)
    maxp = b.get("max_paginas", 15)
    s = session or requests.Session()
    out: list[Vaga] = []
    erros: list[str] = []

    consultas: Iterable[tuple[str, str | None, str | None]] = (
        [(t, c, None) for c in loc["prioridade_1"] + loc["prioridade_2"] for t in b["gupy_termos_por_cidade"]]
        + [(t, None, "remote") for t in b["gupy_termos_remotos"]]
    )
    for termo, cidade, wt in consultas:
        try:
            out.extend(buscar(termo, city=cidade, workplace_type=wt, max_paginas=maxp, pausa=pausa, session=s))
        except Exception as e:  # noqa: BLE001
            erros.append(f"gupy '{termo}' {cidade or wt}: {e}")
            log.warning("falha gupy %s %s: %s", termo, cidade or wt, e)
        time.sleep(pausa)
    return out, erros
