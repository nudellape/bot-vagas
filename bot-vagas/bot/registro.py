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

COLUNAS = [
    "ID", "Fonte", "Empresa", "Vaga", "Cidade", "Modalidade", "Carga horária", "Cursos aceitos",
    "Bolsa e benefícios", "Publicação", "Prazo", "Nota", "Detalhe da nota", "Alertas", "Link",
    "Verificação", "Data da descoberta", "Última vez vista", "Status", "Minhas notas",
]
STATUS_VALIDOS = ["nova", "analisar", "candidatura enviada", "entrevista", "encerrada", "descartada"]
COLUNAS_DA_NU = {"Status", "Minhas notas"}


def vaga_para_linha(v: Vaga, hoje: str) -> dict:
    return {
        "ID": v.id, "Fonte": v.fonte, "Empresa": v.empresa, "Vaga": v.titulo,
        "Cidade": ", ".join(x for x in [v.cidade, v.estado] if x) or "não informada",
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
    """Retorna (linhas_finais, novas, mudancas).
    encontradas = vagas filtradas para registrar/atualizar.
    ids_abertos = TODOS os IDs devolvidos pelas fontes (inclusive fora dos filtros),
                  usados para decidir se uma vaga registrada continua aberta.
    fontes_ok   = prefixos de ID cuja consulta foi completa (ex.: {'gupy:'});
                  só eles podem marcar vagas como sumidas."""
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

    linhas = sorted(por_id.values(), key=lambda r: (-int(r.get("Nota") or 0), r.get("Empresa", "")))
    return linhas, novas, mudancas


# ------------------------------------------------------------- back-ends

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
    """Planilha Google. Usa conta de serviço (JSON na variável GOOGLE_SERVICE_ACCOUNT_JSON)
    e o ID da planilha em SHEET_ID. A aba 'Vagas' é criada se não existir."""

    ABA = "Vagas"

    def __init__(self, sheet_id: str, credenciais_json: str):
        import gspread  # import tardio: só exige a lib quando usar Sheets
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_info(
            json.loads(credenciais_json), scopes=["https://www.googleapis.com/auth/spreadsheets"])
        self.planilha = gspread.authorize(creds).open_by_key(sheet_id)
        try:
            self.aba = self.planilha.worksheet(self.ABA)
        except gspread.WorksheetNotFound:
            self.aba = self.planilha.add_worksheet(self.ABA, rows=1000, cols=len(COLUNAS))
            self._formatar()

    def _formatar(self):
        self.aba.update([COLUNAS], "A1")
        self.aba.freeze(rows=1)
        self.aba.format("1:1", {"textFormat": {"bold": True}})
        # lista suspensa na coluna Status
        col = COLUNAS.index("Status")
        self.planilha.batch_update({"requests": [{"setDataValidation": {
            "range": {"sheetId": self.aba.id, "startRowIndex": 1, "startColumnIndex": col, "endColumnIndex": col + 1},
            "rule": {"condition": {"type": "ONE_OF_LIST",
                                   "values": [{"userEnteredValue": s} for s in STATUS_VALIDOS]},
                     "showCustomUi": True, "strict": False}}}]})

    def ler(self) -> list[dict]:
        if self.aba.row_values(1) != COLUNAS:  # aba vazia ou criada à mão
            self._formatar()
            return []
        return self.aba.get_all_records(expected_headers=COLUNAS, default_blank="")

    def gravar(self, linhas: list[dict]) -> None:
        valores = [COLUNAS] + [[r.get(c, "") for c in COLUNAS] for r in linhas]
        if self.aba.row_count < len(valores):
            self.aba.add_rows(len(valores) - self.aba.row_count + 100)
        self.aba.batch_clear([f"A2:T{max(self.aba.row_count, 2)}"])
        self.aba.update(valores, "A1", value_input_option="RAW")


def abrir_registro():
    sid, cred = os.getenv("SHEET_ID"), os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sid and cred:
        return RegistroSheets(sid, cred)
    return RegistroCSV(os.getenv("CSV_PATH", "dados/vagas.csv"))
