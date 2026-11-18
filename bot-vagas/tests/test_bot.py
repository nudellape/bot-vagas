"""Testes offline (sem internet): simulam respostas da Gupy."""
from datetime import date

import pytest

from bot import analise, main, registro
from bot.models import Vaga
from bot.sources import gupy

HOJE = date(2026, 11, 17)
CFG = main.carregar_config()


def job(id_, name, city="Campinas", wt="hybrid", desc="", pub="2026-11-14", prazo="2026-11-30",
        tipo="vacancy_type_internship", empresa="Empresa X"):
    return {"id": id_, "name": name, "careerPageName": empresa, "city": city, "state": "São Paulo",
            "workplaceType": wt, "description": desc, "publishedDate": pub + "T10:00:00.000Z",
            "applicationDeadline": prazo + "T00:00:00.000Z" if prazo else None,
            "jobUrl": f"https://x.gupy.io/job/{id_}", "type": tipo}


class FakeResp:
    def __init__(self, data):
        self._d = data
    def raise_for_status(self):
        pass
    def json(self):
        return self._d


class FakeSession:
    """Devolve os jobs só para a primeira consulta de cada cidade; o resto vem vazio."""
    def __init__(self, jobs, falhar=False):
        self.jobs, self.falhar, self.chamadas = jobs, falhar, 0
    def get(self, url, params=None, **kw):
        self.chamadas += 1
        if self.falhar:
            raise ConnectionError("simulado")
        if "gupy" not in url:
            return FakeResp({"content": [], "totalFound": 0, "data": []})
        if params.get("offset", 0) == 0 and params.get("city") == "Campinas" and params["jobName"] == "estágio":
            return FakeResp({"data": self.jobs, "pagination": {"total": len(self.jobs)}})
        return FakeResp({"data": [], "pagination": {"total": 0}})


@pytest.fixture(autouse=True)
def sem_pausa(monkeypatch):
    monkeypatch.setattr(gupy.time, "sleep", lambda *_: None)


# ---------------------------------------------------------------- nota

def test_vaga_ideal_tem_nota_alta():
    v = gupy._to_vaga(job(1, "Estágio em Planejamento e PMO", desc=(
        "Requisitos: cursando Engenharia Agrícola, Produção ou áreas afins. Formatura entre 2027 e 2028. "
        "Excel avançado e Power BI. Jornada de 30 horas semanais. Bolsa de R$ 2.200,00, vale-transporte, "
        "assistência médica. Programa de estágio com mentoria e treinamento.")))
    analise.pontuar(v, CFG, HOJE)
    assert v.nota >= 90, v.detalhe_nota
    assert v.carga_horaria == "30h/semana"
    assert "R$ 2.200,00" in v.bolsa_beneficios
    assert v.alertas == []
    assert v.recente


def test_curso_e_jornada_desconhecidos_ficam_no_meio():
    v = gupy._to_vaga(job(2, "Estágio em Supply Chain", desc="Atuar com fornecedores."))
    analise.pontuar(v, CFG, HOJE)
    assert "DESCONHECIDO" in v.detalhe_nota and "DESCONHECIDA" in v.detalhe_nota
    assert 50 <= v.nota <= 70


def test_formatura_incompativel_gera_alerta():
    v = gupy._to_vaga(job(3, "Estágio em Dados", desc="Formatura prevista até dezembro de 2027. Engenharias."))
    analise.pontuar(v, CFG, HOJE)
    assert any("formatura até 2027" in a for a in v.alertas)


def test_curso_listado_sem_engenharia_gera_alerta():
    v = gupy._to_vaga(job(4, "Estágio Financeiro", desc="Cursando Administração, Economia ou Contábeis."))
    analise.pontuar(v, CFG, HOJE)
    assert any("Curso" in a for a in v.alertas)


def test_40h_penaliza_jornada():
    v = gupy._to_vaga(job(5, "Estágio Qualidade", desc="Horário: 8 horas por dia."))
    analise.pontuar(v, CFG, HOJE)
    assert "Jornada 3/15" in v.detalhe_nota


def test_bi_nao_casa_com_biologia_e_intern_nao_casa_com_interno():
    assert analise.eh_estagio(Vaga(id="a", fonte="t", empresa="", titulo="Analista Interno", tipo="vacancy_type_effective")) is False
    assert analise.eh_estagio(Vaga(id="b", fonte="t", empresa="", titulo="Data Intern", tipo="")) is True
    from bot.text import contains_any
    assert contains_any("estagio em biologia", ["bi"]) == []
    assert contains_any("estagio em bi e dados", ["bi"]) == ["bi"]


# ------------------------------------------------------- pipeline + registro

def test_fluxo_completo_csv(tmp_path, monkeypatch):
    monkeypatch.setenv("CSV_PATH", str(tmp_path / "vagas.csv"))
    jobs = [
        job(10, "Estágio em Melhoria Contínua", desc="Engenharias. 6 horas por dia."),
        job(10, "Estágio em Melhoria Contínua", desc="Engenharias. 6 horas por dia."),       # duplicata
        job(11, "Analista de Dados Pleno", tipo="vacancy_type_effective"),                     # não é estágio
        job(12, "Estágio em Logística", city="Recife", wt="on-site"),                          # fora da região
        job(13, "Estágio Sustentabilidade", pub="2026-09-01"),                                 # fora da janela
        job(14, "Estágio em Operações", city="Paulínia", wt="on-site", desc="30 horas semanais."),
    ]
    brutas, erros, ok = main.coletar_tudo(CFG, FakeSession(jobs))
    assert erros == [] and "gupy:" in ok
    vagas, ids = main.processar(brutas, CFG, HOJE)
    assert sorted(v.id for v in vagas) == ["gupy:10", "gupy:14"]

    reg = registro.abrir_registro()
    linhas, novas, mud = registro.mesclar(reg.ler(), vagas, ok, "2026-11-17", ids)
    reg.gravar(linhas)
    assert len(novas) == 2 and all(r["Status"] == "nova" for r in novas)

    # Nu marca uma candidatura; no dia seguinte a vaga 14 some e a 10 continua
    lidas = reg.ler()
    for r in lidas:
        if r["ID"] == "gupy:14":
            r["Status"] = "candidatura enviada"
            r["Minhas notas"] = "enviei dia 17"
    reg.gravar(lidas)

    brutas2, _, ok2 = main.coletar_tudo(CFG, FakeSession([jobs[0], job(15, "Estágio PMO")]))
    vagas2, ids2 = main.processar(brutas2, CFG, HOJE)
    linhas2, novas2, mud2 = registro.mesclar(reg.ler(), vagas2, ok2, "2026-11-18", ids2)
    reg.gravar(linhas2)
    por_id = {r["ID"]: r for r in reg.ler()}

    assert [r["ID"] for r in novas2] == ["gupy:15"]                       # só a nova é alertada
    assert por_id["gupy:14"]["Status"] == "candidatura enviada"           # status da Nu preservado
    assert por_id["gupy:14"]["Minhas notas"] == "enviei dia 17"
    assert por_id["gupy:14"]["Verificação"].startswith("não listada")
    assert por_id["gupy:10"]["Data da descoberta"] == "2026-11-17"        # descoberta original mantida
    assert any("saiu da fonte" in m for m in mud2)


def test_falha_de_fonte_nao_encerra_vagas(tmp_path, monkeypatch):
    monkeypatch.setenv("CSV_PATH", str(tmp_path / "vagas.csv"))
    reg = registro.abrir_registro()
    v = gupy._to_vaga(job(20, "Estágio Dados"))
    analise.pontuar(v, CFG, HOJE)
    linhas, _, _ = registro.mesclar([], [v], {"gupy:"}, "2026-11-17")
    reg.gravar(linhas)

    brutas, erros, ok = main.coletar_tudo(CFG, FakeSession([], falhar=True))
    assert erros and "gupy:" not in ok
    linhas2, _, mud = registro.mesclar(reg.ler(), [], ok, "2026-11-18")
    assert linhas2[0]["Status"] == "nova" and mud == []


def test_texto_do_alerta():
    from bot import alertas
    r = registro.vaga_para_linha(analise.pontuar(gupy._to_vaga(job(30, "Estágio <PMO>")), CFG, HOJE), "2026-11-17")
    r["Nota"] = 80
    t = alertas.montar_texto([r], ["X: prazo mudou"], [], 55, "17/11/2026")
    assert "&lt;PMO&gt;" in t and "Mudanças" in t
    assert alertas.montar_texto([], [], [], 55, "17/11/2026") is None
