"""Fonte: alertas de vaga que chegam por e-mail (Glassdoor e Indeed).

Um Google Apps Script no Gmail de Nu (extras/alertas_email.gs) lê esses e-mails todo dia
e escreve uma linha por vaga na aba "Alertas e-mail" da planilha do robô:
    ID | Fonte | Vaga | Empresa | Cidade | Link | Recebido em
Esta fonte só lê essa aba. As vagas passam pelos mesmos filtros (região, área, janela)
e entram como NÃO CONFIRMADAS: o e-mail não diz prazo nem descrição.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta

from ..models import Vaga

log = logging.getLogger(__name__)

VERIFICACAO = "alerta por e-mail ({fonte}), não confirmada: abra a vaga e confira prazo e requisitos"


def _data(valor) -> date | None:
    s = str(valor or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None


def vagas_das_linhas(linhas: list[dict], hoje: date, dias: int = 30) -> list[Vaga]:
    """Rows of the sheet tab -> Vaga objects (only rows received in the last `dias` days)."""
    out = []
    limite = hoje - timedelta(days=dias)
    for r in linhas:
        vid, titulo, link = str(r.get("ID", "")).strip(), str(r.get("Vaga", "")).strip(), str(r.get("Link", "")).strip()
        if not (vid and titulo and link.startswith("http")):
            continue
        recebido = _data(r.get("Recebido em"))
        if recebido and recebido < limite:
            continue
        fonte = str(r.get("Fonte", "") or "e-mail").strip()
        out.append(Vaga(
            id=f"email:{vid}",
            fonte=f"{fonte} (e-mail)",
            empresa=str(r.get("Empresa", "")).strip() or "não informada",
            titulo=titulo,
            cidade=str(r.get("Cidade", "")).strip(),
            link=link,
            publicada_em=recebido.isoformat() if recebido else "",
            verificacao=VERIFICACAO.format(fonte=fonte),
        ))
    return out


ARQUIVO = os.path.join(os.path.dirname(__file__), "..", "..", "dados", "alertas_email.json")


def _do_arquivo(hoje: date, dias: int) -> list[Vaga]:
    """Rows saved in the repo (e.g. read from Gmail by hand before the script is installed)."""
    try:
        with open(ARQUIVO, encoding="utf-8") as f:
            return vagas_das_linhas(json.load(f), hoje, dias)
    except (OSError, ValueError):
        return []


def coletar(cfg: dict, session=None):
    """Returns (vagas, avisos, fontes_ok, ids). Never marks anything as closed: e-mail can't confirm that."""
    c = cfg.get("alertas_email") or {}
    if not c.get("ativo", True):
        return [], [], set(), set()
    # the saved file only counts in production (tests and local runs stay deterministic)
    do_arquivo = _do_arquivo(date.today(), int(c.get("dias", 30))) if os.getenv("SHEET_ID") else []
    v, avisos, ok, ids = _coletar_planilha(c)
    return do_arquivo + v, avisos, ok, ids | {x.id for x in do_arquivo}


def _coletar_planilha(c: dict):
    sid, cred = os.getenv("SHEET_ID"), os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not (sid and cred):
        return [], [], set(), set()  # local run without the sheet
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_info(
            json.loads(cred), scopes=["https://www.googleapis.com/auth/spreadsheets"])
        planilha = gspread.authorize(creds).open_by_key(sid)
        try:
            aba = planilha.worksheet(c.get("aba", "Alertas e-mail"))
        except gspread.WorksheetNotFound:
            return [], [], set(), set()  # script not installed yet
        vagas = vagas_das_linhas(aba.get_all_records(), date.today(), int(c.get("dias", 30)))
        log.info("alertas por e-mail: %d vagas na aba", len(vagas))
        return vagas, [], set(), {v.id for v in vagas}
    except Exception as e:  # noqa: BLE001 - extra source: failure only goes to the log
        return [], [f"alertas por e-mail: {e}"], set(), set()
