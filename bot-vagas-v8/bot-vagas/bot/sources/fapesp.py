"""Fonte: Agência FAPESP — Oportunidades (bolsas de iniciação científica e
treinamento técnico em universidades e institutos).

Lê a listagem pública https://agencia.fapesp.br/oportunidades/ (páginas 1..N),
fica só com bolsas de INICIAÇÃO CIENTÍFICA / TREINAMENTO TÉCNICO / estágio em
instituições da região (Unicamp, CNPEM, Embrapa, Ital, IAC, CPqD, CTI...) e abre
cada notícia para ler prazo, requisitos e o link oficial (fapesp.br/oportunidades/NNNN).
Bolsa não é estágio formal, mas costuma ter horário flexível e conta como experiência.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date

import requests

from ..models import Vaga
from ..text import norm, strip_html

log = logging.getLogger(__name__)
BASE = "https://agencia.fapesp.br"
HEADERS = {"User-Agent": "Mozilla/5.0 (bot pessoal de busca de estágio)", "Accept": "text/html"}

# palavra-chave no título/texto -> cidade
INSTITUICOES = [
    ("limeira", "Limeira"), ("piracicaba", "Piracicaba"), ("sao carlos", "São Carlos"),
    ("embrapa meio ambiente", "Jaguariúna"), ("embrapa instrumentacao", "Jaguariúna"),
    ("jaguariuna", "Jaguariúna"), ("paulinia", "Paulínia"), ("sumare", "Sumaré"),
    ("hortolandia", "Hortolândia"), ("valinhos", "Valinhos"), ("vinhedo", "Vinhedo"),
    ("unicamp", "Campinas"), ("cnpem", "Campinas"), ("sirius", "Campinas"), ("lnls", "Campinas"),
    ("lnbr", "Campinas"), ("lnnano", "Campinas"), ("ital", "Campinas"),
    ("instituto agronomico", "Campinas"), ("iac", "Campinas"), ("cpqd", "Campinas"),
    ("cti renato archer", "Campinas"), ("puc-campinas", "Campinas"), ("puc campinas", "Campinas"),
    ("embrapa agricultura digital", "Campinas"), ("embrapa territorial", "Campinas"), ("campinas", "Campinas"),
]
NIVEL = re.compile(r"iniciacao cientifica|treinamento tecnico|estagi|\bic\b|\btt-?[1-3]\b")
MESES = {m: i for i, m in enumerate(["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
                                      "agosto", "setembro", "outubro", "novembro", "dezembro"], 1)}


def cidade_por_instituicao(texto_n: str) -> str:
    for chave, cidade in INSTITUICOES:
        if re.search(rf"(?<![a-z]){re.escape(chave)}(?![a-z])", texto_n):
            return cidade
    return ""


def links_da_listagem(html: str) -> list[tuple[str, str]]:
    """Retorna [(url, título)] das notícias da página de listagem."""
    vistos: dict[str, str] = {}
    for href, texto in re.findall(r'<a[^>]+href="((?:https://agencia\.fapesp\.br)?/[a-z0-9\-]+/\d{4,6}/?)"[^>]*>(.*?)</a>',
                                  html, flags=re.S | re.I):
        url = href if href.startswith("http") else BASE + href
        titulo = strip_html(texto)
        if len(titulo) > len(vistos.get(url, "")):
            vistos[url] = titulo
    return [(u, t) for u, t in vistos.items() if t]


def data_extensa(texto_n: str) -> str:
    m = re.search(r"(\d{1,2}) de (" + "|".join(MESES) + r") de (20\d\d)", texto_n)
    if not m:
        return ""
    return date(int(m.group(3)), MESES[m.group(2)], int(m.group(1))).isoformat()


def prazo_do_texto(texto_n: str, publicada: str) -> str:
    """'inscrições até 30/04' / 'até a próxima quarta-feira (30/04)' -> AAAA-MM-DD (ano da publicação)."""
    m = re.search(r"(?:ate|encerra[m]? em|termina[m]?)[^.\n]{0,60}?(\d{1,2})/(\d{1,2})(?:/(20\d\d))?", texto_n)
    if not m:
        return ""
    ano = int(m.group(3)) if m.group(3) else int((publicada or str(date.today()))[:4])
    try:
        d = date(ano, int(m.group(2)), int(m.group(1)))
    except ValueError:
        return ""
    if publicada and d.isoformat() < publicada:  # prazo em janeiro de notícia de dezembro
        d = date(ano + 1, d.month, d.day)
    return d.isoformat()


def coletar(cfg: dict, session: requests.Session | None = None):
    conf = cfg.get("fapesp") or {}
    if not conf.get("ativo", True):
        return [], [], set(), set()
    s = session or requests.Session()
    loc = cfg["localizacao"]
    alvo = {norm(c) for c in loc["prioridade_1"] + loc["prioridade_2"]}
    paginas = conf.get("paginas", 3)
    pausa = cfg["busca"].get("pausa_entre_requisicoes_seg", 1.0)
    hoje = date.today()
    out, avisos = [], []

    candidatos: list[tuple[str, str]] = []
    for p in range(1, paginas + 1):
        url = f"{BASE}/oportunidades/" if p == 1 else f"{BASE}/oportunidades/{p}"
        try:
            r = s.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            candidatos += links_da_listagem(r.text)
        except Exception as e:  # noqa: BLE001
            avisos.append(f"fapesp listagem {url}: {e}")
            break
        time.sleep(pausa)

    vistos = set()
    for url, titulo in candidatos:
        tn = norm(titulo)
        if url in vistos or not NIVEL.search(tn):
            continue
        vistos.add(url)
        cidade = cidade_por_instituicao(tn)
        if cidade and norm(cidade) not in alvo:
            continue
        try:
            html = s.get(url, headers=HEADERS, timeout=30).text
        except Exception as e:  # noqa: BLE001
            avisos.append(f"fapesp notícia {url}: {e}")
            continue
        texto = strip_html(re.sub(r"(?is)<(script|style|nav|footer|header).*?</\1>", " ", html))
        texto_n = norm(texto)
        if not cidade:
            cidade = cidade_por_instituicao(texto_n[:3000])
        if norm(cidade) not in alvo:
            continue
        publicada = data_extensa(texto_n[:3000])
        prazo = prazo_do_texto(texto_n, publicada)
        if prazo and prazo < hoje.isoformat():
            continue  # inscrições já encerradas
        oficial = re.search(r"(?:https?://)?www\.fapesp\.br/oportunidades/(\d+)/?", texto)
        link = f"https://www.fapesp.br/oportunidades/{oficial.group(1)}/" if oficial else url
        vid = f"fapesp:{oficial.group(1) if oficial else url.rstrip('/').rsplit('/', 1)[-1]}"
        out.append(Vaga(id=vid, fonte="fapesp", empresa="Bolsa FAPESP", titulo=titulo, cidade=cidade,
                        descricao=texto[:6000], publicada_em=publicada, prazo=prazo, link=link, tipo="bolsa",
                        verificacao=("aberta: prazo de inscrição " + prazo) if prazo else
                        "NÃO CONFIRMADA: notícia sem prazo identificado"))
        time.sleep(pausa)
    log.info("fapesp: %d bolsas na região", len(out))
    return out, avisos, set(), set()
