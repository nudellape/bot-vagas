"""Envio de alertas por Telegram e/ou e-mail. Cada canal só é usado se as
variáveis de ambiente correspondentes existirem."""
from __future__ import annotations

import html
import logging
import os
import smtplib
from email.mime.text import MIMEText

import requests

from .registro import iso_para_br

log = logging.getLogger(__name__)


def montar_texto(novas: list[dict], mudancas: list[str], erros: list[str], limiar: int, hoje: str) -> str | None:
    relevantes = [r for r in novas if int(r["Nota"]) >= limiar]
    if not relevantes and not mudancas and not erros:
        return None
    linhas = [f"<b>◆ Radar de estágios · {hoje}</b>"]
    if relevantes:
        linhas.append(f"\n<b>{len(relevantes)} nova(s) com nota ≥ {limiar}</b>")
        for r in sorted(relevantes, key=lambda x: -int(x["Nota"]))[:15]:
            e = lambda s: html.escape(str(s))  # noqa: E731
            linhas.append(
                f"\n<b>{e(r['Nota'])}</b> · [{e(r.get('Tipo', 'Estágio'))}] {e(r['Empresa'])}: <a href=\"{e(r['Link'])}\">{e(r['Vaga'])}</a>\n"
                f"{e(r['Cidade'])} · {e(r['Modalidade'])} · {e(r['Carga horária'])}\n"
                f"Publicação: {e(iso_para_br(r['Publicação']))} · Prazo: {e(iso_para_br(r['Prazo']))}"
                + (f"\n⚠ {e(r['Alertas'])}" if r.get("Alertas") else ""))
    abaixo = len(novas) - len(relevantes)
    if abaixo:
        linhas.append(f"\n{abaixo} nova(s) abaixo do limiar registrada(s) só na planilha.")
    if mudancas:
        linhas.append("\n<b>Mudanças</b>")
        linhas += [f"• {html.escape(m)}" for m in mudancas[:20]]
    if erros:
        linhas.append(f"\n<b>Falhas de coleta ({len(erros)})</b>: vagas dessas consultas não foram verificadas hoje.")
        linhas += [f"• {html.escape(x)[:180]}" for x in erros[:5]]
    return "\n".join(linhas)


def enviar_telegram(texto: str) -> bool:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    # Telegram limita mensagens a 4096 caracteres
    partes, atual = [], ""
    for bloco in texto.split("\n\n"):
        if len(atual) + len(bloco) > 3800:
            partes.append(atual)
            atual = ""
        atual += bloco + "\n\n"
    partes.append(atual)
    for p in partes:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": p, "parse_mode": "HTML",
                                "disable_web_page_preview": True}, timeout=30)
        r.raise_for_status()
    return True


def enviar_email(texto: str, assunto: str) -> bool:
    host, user, pwd, dest = (os.getenv(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"))
    if not (host and user and pwd and dest):
        return False
    msg = MIMEText(texto.replace("\n", "<br>"), "html", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = assunto, user, dest
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT") or 587), timeout=30) as s:
        s.starttls()
        s.login(user, pwd)
        s.sendmail(user, [d.strip() for d in dest.split(",")], msg.as_string())
    return True


def enviar(texto: str, assunto: str) -> list[str]:
    canais = []
    for nome, fn in (("telegram", lambda: enviar_telegram(texto)), ("email", lambda: enviar_email(texto, assunto))):
        try:
            if fn():
                canais.append(nome)
        except Exception as e:  # noqa: BLE001
            log.error("falha ao enviar %s: %s", nome, e)
    return canais
