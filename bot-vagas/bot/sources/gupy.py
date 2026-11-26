"""Fonte: portal público de vagas da Gupy (portal.gupy.io).

Usa o endpoint interno que alimenta o próprio portal (não documentado; pode mudar):
    GET https://portal.gupy.io/api/job-search/jobs?jobName=...&limit=..&offset=..
O endereço antigo (portal.api.gupy.io / employability-portal.gupy.io) passou a
responder 404 em out/2026; fica como reserva caso volte.
Não requer login. O portal lista apenas vagas com inscrições abertas, então
"aparecer na busca" é a evidência de que a vaga está aberta naquele momento.

O filtro `workplaceType` NÃO é enviado (a API responde 404 com ele); vagas
remotas são separadas localmente. Se uma consulta falhar, o bot tenta de novo
sem acento e, por último, sem o filtro de cidade (o filtro local cuida disso).
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
_endpoint_ok: str | None = None  # memoriza o endereço que funcionou nesta execução

# Remote filter: the portal's parameter name is not documented. Probe these (endpoint, params) once per
# run and keep the first that really returns remote jobs (>= 80% of a page).
CANDIDATOS_REMOTO = [
    ("https://portal.gupy.io/api/job-search/jobs", {"workplaceType": "remote"}),
    ("https://portal.gupy.io/api/job-search/jobs", {"workplaceTypes": "remote"}),
    ("https://portal.gupy.io/api/job-search/jobs", {"isRemoteWork": "true"}),
    ("https://portal.api.gupy.io/api/v1/jobs", {"workplaceType": "remote"}),
    ("https://employability-portal.gupy.io/api/v1/jobs", {"workplaceType": "remote"}),
    ("https://portal.gupy.io/api/job-search/jobs", {"workplaceTypes[]": "remote"}),
]
_remoto_ok: tuple[str, dict] | None | bool = None  # None = not probed; False = nothing works


def descobrir_filtro_remoto(s: requests.Session, pausa: float = 0.5) -> tuple[str, dict] | None:
    global _remoto_ok
    if _remoto_ok is not None:
        return _remoto_ok or None
    for url, extra in CANDIDATOS_REMOTO:
        try:
            r = s.get(url, params={"jobName": "estágio", "limit": PAGE, "offset": 0, **extra}, headers=HEADERS, timeout=30)
            if getattr(r, "status_code", 200) >= 400:
                log.info("filtro remoto %s %s: HTTP %s", url, extra, r.status_code)
                continue
            dados = (r.json() or {}).get("data") or []
            remotas = sum(_to_vaga(j).modalidade == "remoto" for j in dados)
            log.info("filtro remoto %s %s: %d/%d remotas", url, extra, remotas, len(dados))
            if dados and remotas >= 0.8 * len(dados):
                _remoto_ok = (url, extra)
                return _remoto_ok
        except Exception as e:  # noqa: BLE001
            log.info("filtro remoto %s %s: %s", url, extra, e)
        time.sleep(pausa)
    _remoto_ok = False
    return None
PAGE = 10  # tamanho de página aceito pelo portal
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
             s: requests.Session, remoto: bool = False) -> list[Vaga]:
    vagas: list[Vaga] = []
    for pagina in range(max_paginas):
        params = {"jobName": job_name, "limit": PAGE, "offset": pagina * PAGE}
        if city:
            params["city"] = city
        if remoto and isinstance(_remoto_ok, tuple):
            params.update(_remoto_ok[1])
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
           session: requests.Session | None = None, remoto: bool = False) -> list[Vaga]:
    """Tenta: (termo, cidade) -> (termo sem acento, cidade) -> (termo sem acento, sem cidade).
    With remoto=True, first asks the portal for remote jobs only, then falls back to no filter.
    Lança a última exceção se todas falharem."""
    s = session or requests.Session()
    sem_acento = norm(job_name)
    tentativas = [(job_name, city, False)]
    if sem_acento != job_name.lower():
        tentativas.append((sem_acento, city, False))
    if city:
        tentativas.append((sem_acento, None, False))
    if remoto:
        tentativas.insert(0, (job_name, city, True))
    global _endpoint_ok
    urls = [_endpoint_ok] if _endpoint_ok else ENDPOINTS
    if remoto:
        achado = descobrir_filtro_remoto(s)
        if achado:
            urls = [achado[0]]
            tentativas = [(job_name, city, True)]
        else:
            tentativas = [t for t in tentativas if not t[2]]
    ultimo_erro: Exception | None = None
    for url in urls:
        for termo, cid, rem in tentativas:
            try:
                vagas = _paginar(url, termo, cid, max_paginas, pausa, s, rem)
                if not rem:
                    _endpoint_ok = url
                log.info("gupy %s jobName=%r city=%r remoto=%s -> %d (remotas: %d)", url, termo, cid, rem,
                         len(vagas), sum(v.modalidade == "remoto" for v in vagas))
                return vagas
            except Exception as e:  # noqa: BLE001
                ultimo_erro = e
                log.info("tentativa falhou (%s jobName=%r city=%r): %s", url, termo, cid, e)
                time.sleep(pausa)
    raise ultimo_erro  # type: ignore[misc]


def coletar(cfg: dict, session: requests.Session | None = None) -> tuple[list[Vaga], list[str]]:
    """Executa todas as consultas configuradas. Retorna (vagas, erros)."""
    b = cfg["busca"]
    loc = cfg["localizacao"]
    pausa = b.get("pausa_entre_requisicoes_seg", 1.0)
    maxp = b.get("max_paginas", 15)
    s = session or requests.Session()
    out: list[Vaga] = []
    erros: list[str] = []

    termos_cidade = list(b["gupy_termos_por_cidade"])
    if b.get("incluir_empregos"):
        termos_cidade += b.get("gupy_termos_emprego_por_cidade", [])
    consultas = ([(t, c) for c in loc["prioridade_1"] + loc["prioridade_2"] for t in termos_cidade]
                 + [(t, c) for c in loc.get("hibrido_ok", []) for t in b.get("gupy_termos_hibrido_ok", [])]
                 + [(t, None) for t in b["gupy_termos_remotos"]])
    consultas = [(t, c, False, maxp) for t, c in consultas]
    # every remote internship in Brazil: broad terms, remote filter, more pages
    consultas += [(t, None, True, b.get("max_paginas_remoto", 40)) for t in b.get("gupy_termos_estagio_remoto", [])]
    for termo, cidade, remoto, paginas in consultas:
        try:
            out.extend(buscar(termo, city=cidade, max_paginas=paginas, pausa=pausa, session=s, remoto=remoto))
        except Exception as e:  # noqa: BLE001
            erros.append(f"gupy '{termo}' {cidade or 'nacional'}: {e}")
            log.warning("falha gupy %s %s: %s", termo, cidade or "nacional", e)
        time.sleep(pausa)
    return out, erros
