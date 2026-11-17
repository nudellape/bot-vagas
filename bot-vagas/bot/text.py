"""Utilidades de texto."""
from __future__ import annotations

import html
import re
import unicodedata


def strip_html(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def norm(s: str | None) -> str:
    """minúsculas, sem acentos, espaços simples."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip()


def contains_any(text_norm: str, termos: list[str]) -> list[str]:
    """Retorna os termos (normalizados) encontrados no texto já normalizado."""
    achados = []
    for t in termos:
        tn = norm(t)
        if not tn:
            continue
        # fronteira de palavra: "bi" não casa com "ambiental"; "projeto" casa com "projetos"
        padrao = rf"(?<![a-z0-9]){re.escape(tn)}(?:s|es)?(?![a-z0-9])"
        if re.search(padrao, text_norm) and tn not in achados:
            achados.append(tn)
    return achados
