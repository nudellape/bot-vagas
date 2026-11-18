"""Aba 'Painel': resumo visual (tema escuro) reescrito a cada execução.

Mostra indicadores (vagas abertas, novas, nota alta, prazos, candidaturas,
entrevistas), o top 10 e os prazos que vencem em 7 dias. Tudo é calculado em
Python e gravado como valores (sem fórmulas), então funciona em qualquer idioma
de planilha.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

ABA = "Painel"
NCOL = 8   # A..H
NLIN = 40

# paleta
BG, CARD, LINHA = "#0b1220", "#111a2e", "#1e293b"
TEXTO, MUDO, CIANO = "#e2e8f0", "#94a3b8", "#22d3ee"
VERDE, AMBAR, CINZA = "#34d399", "#fbbf24", "#64748b"
MONO = "Roboto Mono"


def _rgb(h):
    h = h.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def _cel(valor="", *, bg=BG, cor=TEXTO, tam=10, negrito=False, fonte=None, alinhar="LEFT", link=None,
         italico=False):
    tf = {"foregroundColor": _rgb(cor), "fontSize": tam, "bold": negrito, "italic": italico}
    if fonte:
        tf["fontFamily"] = fonte
    if link:
        tf["link"] = {"uri": link}
        tf["underline"] = True
    v = {"numberValue": valor} if isinstance(valor, (int, float)) and not isinstance(valor, bool) \
        else {"stringValue": str(valor)}
    return {"userEnteredValue": v, "userEnteredFormat": {
        "backgroundColor": _rgb(bg), "textFormat": tf, "horizontalAlignment": alinhar,
        "verticalAlignment": "MIDDLE", "wrapStrategy": "CLIP"}}


def _data(iso):
    try:
        return date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


def _br(iso):
    d = _data(iso)
    return d.strftime("%d/%m/%Y") if d else str(iso or "")


def _cor_nota(n):
    return VERDE if n >= 75 else AMBAR if n >= 55 else CINZA


def montar(linhas: list[dict], novas: list[dict], agora: datetime):
    hoje = agora.date()
    fim = {"encerrada", "descartada"}
    abertas = [r for r in linhas if str(r.get("Verificação", "")).startswith("aberta") and r.get("Status") not in fim]
    nota = lambda r: int(r.get("Nota") or 0)  # noqa: E731
    urgentes = sorted([r for r in abertas if (d := _data(r.get("Prazo"))) and hoje <= d <= hoje + timedelta(days=7)],
                      key=lambda r: (_data(r["Prazo"]), -nota(r)))
    kpis = [
        ("VAGAS ABERTAS", len(abertas), CIANO),
        ("NOVAS HOJE", len(novas), CIANO),
        ("NOTA ≥ 75", sum(nota(r) >= 75 for r in abertas), VERDE),
        ("PRAZO ≤ 7 DIAS", len(urgentes), AMBAR),
        ("CANDIDATURAS", sum(r.get("Status") == "candidatura enviada" for r in linhas), "#60a5fa"),
        ("ENTREVISTAS", sum(r.get("Status") == "entrevista" for r in linhas), "#c084fc"),
    ]

    g = [[_cel() for _ in range(NCOL)] for _ in range(NLIN)]
    merges = []

    g[0][1] = _cel("◆ RADAR DE ESTÁGIOS", cor=CIANO, tam=18, negrito=True, fonte=MONO)
    merges.append((0, 1, 0, 7))
    g[1][1] = _cel(f"atualizado {agora.strftime('%d/%m/%Y às %H:%M')} · Gupy · 3M · GE Vernova",
                   cor=MUDO, tam=9, fonte=MONO)
    merges.append((1, 1, 1, 7))

    # cartões de indicadores (linhas 4-5)
    for i, (rotulo, valor, cor) in enumerate(kpis):
        c = 1 + i
        g[3][c] = _cel(rotulo, bg=CARD, cor=MUDO, tam=8, negrito=True, fonte=MONO, alinhar="CENTER")
        g[4][c] = _cel(valor, bg=CARD, cor=cor, tam=24, negrito=True, fonte=MONO, alinhar="CENTER")

    def tabela(lin, titulo, itens, vazio):
        g[lin][1] = _cel(titulo, cor=CIANO, tam=11, negrito=True, fonte=MONO)
        merges.append((lin, 1, lin, 7))
        cab = ["NOTA", "EMPRESA", "VAGA", "CIDADE", "PRAZO", "LINK"]
        for j, t in enumerate(cab):
            g[lin + 1][1 + j] = _cel(t, bg=LINHA, cor=MUDO, tam=8, negrito=True, fonte=MONO,
                                     alinhar="CENTER" if j in (0, 4, 5) else "LEFT")
        if not itens:
            g[lin + 2][1] = _cel(vazio, cor=MUDO, italico=True)
            merges.append((lin + 2, 1, lin + 2, 7))
            return lin + 3
        for k, r in enumerate(itens):
            ln = lin + 2 + k
            fundo = CARD if k % 2 == 0 else BG
            n = nota(r)
            g[ln][1] = _cel(n, bg=fundo, cor=_cor_nota(n), tam=12, negrito=True, fonte=MONO, alinhar="CENTER")
            g[ln][2] = _cel(r.get("Empresa", ""), bg=fundo)
            g[ln][3] = _cel(r.get("Vaga", ""), bg=fundo, negrito=True)
            g[ln][4] = _cel(r.get("Cidade", ""), bg=fundo, cor=MUDO)
            g[ln][5] = _cel(_br(r.get("Prazo")), bg=fundo, cor=MUDO, fonte=MONO, alinhar="CENTER")
            url = r.get("URL") or r.get("Link") or ""
            g[ln][6] = _cel("abrir ↗" if url else "", bg=fundo, cor=CIANO, link=url or None, alinhar="CENTER")
        return lin + 2 + len(itens) + 1

    prox = tabela(6, "▸ TOP 10 · MELHORES VAGAS ABERTAS", sorted(abertas, key=lambda r: -nota(r))[:10],
                  "nenhuma vaga aberta no momento")
    tabela(prox, "▸ PRAZOS TERMINANDO NOS PRÓXIMOS 7 DIAS", urgentes[:10], "nenhum prazo vencendo nesta semana")
    return g, merges


def atualizar_painel(planilha, linhas: list[dict], novas: list[dict], agora: datetime) -> None:
    import gspread
    try:
        aba = planilha.worksheet(ABA)
    except gspread.WorksheetNotFound:
        aba = planilha.add_worksheet(ABA, rows=NLIN, cols=NCOL, index=0)
    sid = aba.id
    g, merges = montar(linhas, novas, agora)

    larguras = [24, 90, 190, 380, 120, 110, 90, 24]
    req = [
        {"updateSheetProperties": {"properties": {"sheetId": sid, "index": 0, "gridProperties": {
            "hideGridlines": True, "rowCount": NLIN, "columnCount": NCOL, "frozenRowCount": 0}},
            "fields": "index,gridProperties.hideGridlines,gridProperties.rowCount,gridProperties.columnCount,"
                      "gridProperties.frozenRowCount"}},
        {"unmergeCells": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": NLIN,
                                    "startColumnIndex": 0, "endColumnIndex": NCOL}}},
        {"updateCells": {"rows": [{"values": linha} for linha in g], "fields": "userEnteredValue,userEnteredFormat",
                         "start": {"sheetId": sid, "rowIndex": 0, "columnIndex": 0}}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0,
                                                 "endIndex": NLIN}, "properties": {"pixelSize": 28},
                                       "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0,
                                                 "endIndex": 1}, "properties": {"pixelSize": 46},
                                       "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 4,
                                                 "endIndex": 5}, "properties": {"pixelSize": 56},
                                       "fields": "pixelSize"}},
    ]
    for i, px in enumerate(larguras):
        req.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
                                                            "startIndex": i, "endIndex": i + 1},
                                                  "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    for r0, c0, r1, c1 in merges:
        req.append({"mergeCells": {"mergeType": "MERGE_ALL", "range": {
            "sheetId": sid, "startRowIndex": r0, "endRowIndex": r1 + 1, "startColumnIndex": c0, "endColumnIndex": c1}}})
    planilha.batch_update({"requests": req})
