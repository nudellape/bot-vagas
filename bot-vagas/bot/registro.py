"""Registro de vagas: Google Sheets (produção) ou CSV local (teste).

Regras de atualização (o histórico nunca é apagado):
- Vaga nova           -> entra com Status = "nova" e Data da descoberta = hoje.
- Vaga já registrada  -> atualiza dados e "Última vez vista"; NÃO mexe em
                         Status nem em Minhas notas (colunas da Nu).
- Vaga que sumiu da fonte (e a fonte foi consultada sem erro)
                      -> Verificação = "não listada na fonte desde <data>".
                         Se o Status era "nova"/"analisar", vira "encerrada".
                         Status de candidaturas/entrevistas não é alterado.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

from .models import Vaga

# Ordem pensada para leitura: o que importa primeiro; colunas técnicas no fim (ocultas).
COLUNAS = [
    "Nota", "Status", "Empresa", "Vaga", "Cidade", "Modalidade", "Prazo", "Link", "Alertas",
    "Carga horária", "Cursos aceitos", "Bolsa e benefícios", "Publicação", "Minhas notas",
    "Detalhe da nota", "Verificação", "Data da descoberta", "Última vez vista", "Fonte", "ID",
]
PRIMEIRA_OCULTA = COLUNAS.index("Detalhe da nota")
STATUS_VALIDOS = ["nova", "analisar", "candidatura enviada", "entrevista", "encerrada", "descartada"]
COLUNAS_DA_NU = {"Status", "Minhas notas"}


def vaga_para_linha(v: Vaga, hoje: str) -> dict:
    return {
        "ID": v.id, "Fonte": v.fonte, "Empresa": v.empresa, "Vaga": v.titulo,
        "Cidade": v.cidade or ("remoto" if v.modalidade == "remoto" else "não informada"),
        "Modalidade": v.modalidade or "não informada",
        "Carga horária": v.carga_horaria, "Cursos aceitos": v.cursos_aceitos,
        "Bolsa e benefícios": v.bolsa_beneficios,
        "Publicação": v.publicada_em or "não verificável", "Prazo": v.prazo or "não divulgado",
        "Nota": v.nota, "Detalhe da nota": v.detalhe_nota, "Alertas": " ".join(v.alertas),
        "Link": v.link,
        "Verificação": f"aberta: listada na fonte em {hoje}",
        "Última vez vista": hoje,
    }


def mesclar(existentes: list[dict], encontradas: list[Vaga], fontes_ok: set[str], hoje: str,
            ids_abertos: set[str] | None = None):
    ids_abertos = set(ids_abertos or ()) | {v.id for v in encontradas}
    por_id = {r["ID"]: dict(r) for r in existentes if r.get("ID")}
    novas: list[dict] = []
    mudancas: list[str] = []
    vistos = set()

    for v in encontradas:
        nova_linha = vaga_para_linha(v, hoje)
        vistos.add(v.id)
        if v.id in por_id:
            antiga = por_id[v.id]
            if antiga.get("Prazo") != nova_linha["Prazo"]:
                mudancas.append(f"{v.empresa} | {v.titulo}: prazo {antiga.get('Prazo')} -> {nova_linha['Prazo']}")
            if str(antiga.get("Verificação", "")).startswith("não listada"):
                mudancas.append(f"{v.empresa} | {v.titulo}: voltou a aparecer na fonte")
                if antiga.get("Status") == "encerrada":
                    nova_linha["Status"] = "analisar"
            for k, val in nova_linha.items():
                antiga[k] = val
        else:
            nova_linha.update({"Data da descoberta": hoje, "Status": "nova", "Minhas notas": ""})
            por_id[v.id] = nova_linha
            novas.append(nova_linha)

    for vid, r in por_id.items():
        if vid in ids_abertos or not any(vid.startswith(p) for p in fontes_ok):
            continue
        if not str(r.get("Verificação", "")).startswith("não listada"):
            r["Verificação"] = f"não listada na fonte desde {hoje}"
            if r.get("Status") in ("nova", "analisar"):
                r["Status"] = "encerrada"
                mudancas.append(f"{r.get('Empresa')} | {r.get('Vaga')}: saiu da fonte (provavelmente encerrada)")
            elif r.get("Status") in ("candidatura enviada", "entrevista"):
                mudancas.append(f"{r.get('Empresa')} | {r.get('Vaga')}: saiu da fonte; seu status '{r.get('Status')}' foi mantido")

    fim = {"encerrada", "descartada"}
    linhas = sorted(por_id.values(), key=lambda r: (r.get("Status") in fim, -int(r.get("Nota") or 0),
                                                    r.get("Empresa", "")))
    return linhas, novas, mudancas


class RegistroCSV:
    def __init__(self, caminho: str = "dados/vagas.csv"):
        self.caminho = Path(caminho)

    def ler(self) -> list[dict]:
        if not self.caminho.exists():
            return []
        with self.caminho.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def gravar(self, linhas: list[dict]) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self.caminho.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction="ignore")
            w.writeheader()
            w.writerows(linhas)


class RegistroSheets:
    ABA = "Vagas"

    def __init__(self, sheet_id: str, credenciais_json: str):
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_info(
            json.loads(credenciais_json), scopes=["https://www.googleapis.com/auth/spreadsheets"])
        self.planilha = gspread.authorize(creds).open_by_key(sheet_id)
        self.precisa_formatar = False
        try:
            self.aba = self.planilha.worksheet(self.ABA)
        except gspread.WorksheetNotFound:
            self.aba = self.planilha.add_worksheet(self.ABA, rows=1000, cols=len(COLUNAS), index=0)
            self.precisa_formatar = True

    def ler(self) -> list[dict]:
        cab = self.aba.row_values(1)
        if cab != COLUNAS:
            self.precisa_formatar = True
        if not cab:
            return []
        return self.aba.get_all_records(default_blank="")

    def gravar(self, linhas: list[dict]) -> None:
        valores = [COLUNAS] + [[r.get(c, "") for c in COLUNAS] for r in linhas]
        if self.aba.row_count < len(valores):
            self.aba.add_rows(len(valores) - self.aba.row_count + 100)
        if self.aba.col_count < len(COLUNAS):
            self.aba.add_cols(len(COLUNAS) - self.aba.col_count)
        from gspread.utils import rowcol_to_a1
        self.aba.batch_clear([f"A1:{rowcol_to_a1(self.aba.row_count, max(len(COLUNAS), self.aba.col_count))}"])
        self.aba.update(valores, "A1", value_input_option="RAW")
        if self.precisa_formatar:
            self._formatar(len(valores))

    def _formatar(self, n_linhas: int):
        sid = self.aba.id
        ncol = len(COLUNAS)
        col = COLUNAS.index
        larguras = {"Nota": 55, "Status": 150, "Empresa": 170, "Vaga": 330, "Cidade": 110,
                    "Modalidade": 95, "Prazo": 90, "Link": 90, "Alertas": 260, "Carga horária": 100,
                    "Cursos aceitos": 200, "Bolsa e benefícios": 220, "Publicação": 90, "Minhas notas": 220}

        def faixa(c0, c1=None, r0=0, r1=None):
            d = {"sheetId": sid, "startColumnIndex": c0, "endColumnIndex": (c1 if c1 is not None else c0 + 1),
                 "startRowIndex": r0}
            if r1 is not None:
                d["endRowIndex"] = r1
            return d

        def cor(h):
            h = h.lstrip("#")
            return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}

        def regra(formula, fmt):
            return {"addConditionalFormatRule": {"index": 0, "rule": {
                "ranges": [faixa(0, ncol, 1)],
                "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]},
                                "format": fmt}}}}

        meta = self.planilha.fetch_sheet_metadata()
        aba_meta = next(x for x in meta["sheets"] if x["properties"]["sheetId"] == sid)
        req = [{"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}}
               for _ in aba_meta.get("conditionalFormats", [])]
        if aba_meta.get("basicFilter"):
            req.append({"clearBasicFilter": {"sheetId": sid}})

        req += [
            {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {
                "frozenRowCount": 1, "frozenColumnCount": 4}},
                "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
            {"repeatCell": {"range": faixa(0, ncol, 1), "cell": {"userEnteredFormat": {
                "wrapStrategy": "CLIP", "verticalAlignment": "MIDDLE", "textFormat": {"fontSize": 10}}},
                "fields": "userEnteredFormat(wrapStrategy,verticalAlignment,textFormat)"}},
            {"repeatCell": {"range": faixa(0, ncol, 0, 1), "cell": {"userEnteredFormat": {
                "backgroundColor": cor("#1f3b4d"), "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
                "textFormat": {"bold": True, "foregroundColor": cor("#ffffff"), "fontSize": 10}}},
                "fields": "userEnteredFormat"}},
            {"repeatCell": {"range": faixa(col("Nota"), None, 1), "cell": {"userEnteredFormat": {
                "horizontalAlignment": "CENTER", "textFormat": {"bold": True, "fontSize": 12}}},
                "fields": "userEnteredFormat(horizontalAlignment,textFormat)"}},
            {"repeatCell": {"range": faixa(col("Alertas"), None, 1), "cell": {"userEnteredFormat": {
                "textFormat": {"foregroundColor": cor("#a61b1b"), "fontSize": 9}}},
                "fields": "userEnteredFormat.textFormat"}},
            {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0,
                                                     "endIndex": 1},
                                           "properties": {"pixelSize": 36}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 1,
                                                     "endIndex": max(n_linhas, 2)},
                                           "properties": {"pixelSize": 26}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
                                                     "startIndex": PRIMEIRA_OCULTA, "endIndex": ncol},
                                           "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
            {"setBasicFilter": {"filter": {"range": faixa(0, ncol, 0)}}},
            {"setDataValidation": {"range": faixa(col("Status"), None, 1), "rule": {
                "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": s} for s in STATUS_VALIDOS]},
                "showCustomUi": True, "strict": False}}},
        ]
        for nome, px in larguras.items():
            i = col(nome)
            req.append({"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                "properties": {"pixelSize": px}, "fields": "pixelSize"}})

        req += [
            regra("=$A2<55", {"textFormat": {"foregroundColor": cor("#8a8a8a")}}),
            regra("=AND($A2>=55,$A2<75)", {"backgroundColor": cor("#fff4cc")}),
            regra("=$A2>=75", {"backgroundColor": cor("#d6f0d9")}),
            regra('=$B2="candidatura enviada"', {"backgroundColor": cor("#d6e6fb")}),
            regra('=$B2="entrevista"', {"backgroundColor": cor("#e6d9f7"), "textFormat": {"bold": True}}),
            regra('=OR($B2="encerrada",$B2="descartada")',
                  {"backgroundColor": cor("#eeeeee"),
                   "textFormat": {"strikethrough": True, "foregroundColor": cor("#9e9e9e")}}),
        ]
        self.planilha.batch_update({"requests": req})


def abrir_registro():
    sid, cred = os.getenv("SHEET_ID"), os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sid and cred:
        return RegistroSheets(sid, cred)
    return RegistroCSV(os.getenv("CSV_PATH", "dados/vagas.csv"))
