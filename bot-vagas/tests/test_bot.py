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
    assert sorted(v.id for v in vagas if v.id.startswith("gupy:")) == ["gupy:10", "gupy:14"]

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


# ------------------------------------------------------ Agrobase e FAPESP

RSS = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"
 xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Est\xc3\xa1gio em agricultura de precis\xc3\xa3o \xe2\x80\x93 Jaguari\xc3\xbana/SP</title>
<link>https://www.agrobase.com.br/estagios/?p=40001</link><guid>https://www.agrobase.com.br/estagios/?p=40001</guid>
<pubDate>Mon, 16 Nov 2026 10:00:00 +0000</pubDate>
<content:encoded><![CDATA[<p>Empresa: Fazenda Modelo</p><p>Cursando Engenharia Agr\xc3\xadcola. 6 horas por dia.</p>]]></content:encoded></item>
<item><title>Est\xc3\xa1gio em vendas \xe2\x80\x93 Cuiab\xc3\xa1/MT</title><link>https://x/?p=2</link>
<pubDate>Mon, 16 Nov 2026 10:00:00 +0000</pubDate></item>
<item><title>Est\xc3\xa1gio antigo \xe2\x80\x93 Campinas/SP</title><link>https://x/?p=3</link>
<pubDate>Mon, 01 Sep 2026 10:00:00 +0000</pubDate></item>
</channel></rss>"""


def test_agrobase_le_feed_filtra_cidade_e_data():
    from bot.sources import agrobase
    alvo = {"campinas", "jaguariuna", "paulinia"}
    vagas = agrobase.ler_feed(RSS, False, alvo, HOJE, 21)
    assert [v.cidade for v in vagas] == ["Jaguariúna"]
    v = vagas[0]
    assert v.id == "agrobase:40001" and v.empresa == "Fazenda Modelo"
    assert v.titulo == "Estágio em agricultura de precisão" and v.verificacao.startswith("NÃO CONFIRMADA")
    analise.pontuar(v, CFG, HOJE)
    assert "Engenharia Agrícola citada" == v.cursos_aceitos and v.carga_horaria == "6h/dia"


LISTA = """<div><a href="/iniciacao-cientifica-em-agricultura-digital-na-unicamp/59001">Iniciação científica em
agricultura digital na Unicamp</a><a href="/pos-doutorado-em-fisica-na-usp/59002">Pós-doutorado em física na USP</a>
<a href="https://agencia.fapesp.br/treinamento-tecnico-na-unicamp-de-limeira/59003">Treinamento técnico na Unicamp de Limeira</a></div>"""
NOTICIA = """<html><body><h1>Iniciação científica em agricultura digital na Unicamp</h1><p>10 de novembro de 2026</p>
<p>Uma vaga de iniciação científica está disponível na Feagri-Unicamp. As inscrições vão até 30/11.</p>
<p>Mais informações em: www.fapesp.br/oportunidades/9901/.</p></body></html>"""


def test_fapesp_listagem_e_noticia(monkeypatch):
    from bot.sources import fapesp
    monkeypatch.setattr(fapesp.time, "sleep", lambda *_: None)

    class R:
        def __init__(s, t): s.text = t; s.status_code = 200
        def raise_for_status(s): pass

    class S:
        def get(s, url, **k):
            return R(LISTA if "/oportunidades" in url else NOTICIA)

    vagas, avisos, ok, ids = fapesp.coletar({**CFG, "fapesp": {"paginas": 1}}, S())
    assert len(vagas) == 1 and ok == set()
    v = vagas[0]
    assert v.cidade == "Campinas" and v.prazo == "2026-11-30" and v.publicada_em == "2026-11-10"
    assert v.link == "https://www.fapesp.br/oportunidades/9901/" and v.id == "fapesp:9901"
    assert analise.eh_estagio(v)


def test_empregos_de_entrada_e_exclusoes():
    ok = gupy._to_vaga(job(50, "Assistente Administrativo Financeiro", tipo="vacancy_type_effective",
                           desc="Ensino superior completo. 44 horas semanais."))
    senior = gupy._to_vaga(job(51, "Analista de Dados Sênior", tipo="vacancy_type_effective"))
    aprendiz = gupy._to_vaga(job(52, "Jovem Aprendiz Administrativo", tipo="vacancy_type_apprentice"))
    assert analise.eh_alvo(ok, CFG) and not analise.eh_alvo(senior, CFG) and not analise.eh_alvo(aprendiz, CFG)
    analise.pontuar(ok, CFG, HOJE)
    assert analise.tipo_vaga(ok) == "Emprego"
    assert any("CLT" in a for a in ok.alertas) and any("graduação completa" in a for a in ok.alertas)
    assert registro.vaga_para_linha(ok, "2026-11-17")["Tipo"] == "Emprego"


def test_agrobase_ignora_bolsas_e_empresas_nao_confundem():
    from bot import painel
    from bot.sources import agrobase
    rss = RSS.replace(b"Est\xc3\xa1gio em agricultura", b"Bolsa de inicia\xc3\xa7\xc3\xa3o cient\xc3\xadfica em agricultura")
    assert agrobase.ler_feed(rss, False, {"jaguariuna"}, HOJE, 21) == []
    linhas = [{"Empresa": "Shellfish Ltda", "Vaga": "x", "Nota": 50, "Status": "nova", "Verificação": "aberta"}]
    assert painel._conta(linhas, ["shell"]) == (0, 0)


def test_vigia_detecta_linhas_novas(tmp_path):
    from bot import vigia

    class R:
        def __init__(s, t): s.text = t
        def raise_for_status(s): pass

    class S:
        def __init__(s, t): s.t = t
        def get(s, url, **k): return R(s.t)

    pag = [{"nome": "OMC", "url": "https://x/estagio", "cidade": "Valinhos"}]
    dia1 = "<html><body><h1>Carreiras</h1><p>Programa de estágio 2026 encerrado</p><script>var vaga=1</script></body></html>"
    dia2 = dia1.replace("</body>", "<p>Inscrições abertas: Programa de Estágio 2027, 30h semanais</p></body>")
    est1, mud1, res1 = vigia.verificar(pag, {}, "17/11/2026", S(dia1))
    assert mud1 == [] and res1[0]["situacao"] == "primeira leitura"
    vigia.gravar_estado(est1, caminho=str(tmp_path / "v.json"))
    est2, mud2, res2 = vigia.verificar(pag, vigia.ler_estado(caminho=str(tmp_path / "v.json")), "18/11/2026", S(dia2))
    assert len(mud2) == 1 and "2027" in mud2[0] and res2[0]["mudou_em"] == "18/11/2026"
    _, mud3, res3 = vigia.verificar(pag, est2, "19/11/2026", S(dia2))
    assert mud3 == [] and res3[0]["situacao"] == "sem novidades" and res3[0]["mudou_em"] == "18/11/2026"
    _, _, res4 = vigia.verificar(pag, {}, "19/11/2026", S("<div id=root></div>"))
    assert "JavaScript" in res4[0]["situacao"]


ALERTA = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Google Alert</title>
<entry><title type="html">&lt;b&gt;Programa de Estágio&lt;/b&gt; 2027 Solvay Paulínia: inscrições abertas</title>
<link href="https://www.google.com/url?rct=j&amp;sa=t&amp;url=https://www.solvay.com/pt-br/estagio-2027&amp;ct=ga"/>
<published>2026-11-16T10:00:00Z</published>
<content type="html">A Solvay abriu o &lt;b&gt;programa de estágio&lt;/b&gt; em Paulínia. Inscrições até 05/12.</content></entry>
<entry><title type="html">Jovem aprendiz em Campinas</title><link href="https://www.google.com/url?url=https://x.com/a"/>
<published>2026-11-16T10:00:00Z</published><content type="html">estágio jovem aprendiz</content></entry>
<entry><title type="html">Programa de estágio encerrado Campinas</title><link href="https://www.google.com/url?url=https://x.com/b"/>
<published>2026-10-01T10:00:00Z</published><content type="html">inscrições até 10/10</content></entry>
</feed>""".encode()


def test_google_alertas():
    from bot.sources import alertas_google
    vagas = alertas_google.ler_feed(ALERTA, ["Campinas", "Paulínia"], "", HOJE)
    assert len(vagas) == 1
    v = vagas[0]
    assert v.link == "https://www.solvay.com/pt-br/estagio-2027" and v.cidade == "Paulínia"
    assert v.prazo == "2026-12-05" and v.empresa == "solvay.com" and analise.eh_alvo(v, CFG)
    assert analise.tipo_vaga(v) == "Programa de estágio"


def test_exclusoes_fora_do_perfil():
    def v(t):
        return gupy._to_vaga(job(1, t, tipo="vacancy_type_effective"))
    assert not analise.eh_alvo(v("AGENTE OPERAÇÕES LEVES (MANOBRISTA/ASSISTENTE)"), CFG)
    assert not analise.eh_alvo(v("Vendedora Interna"), CFG)
    assert not analise.eh_alvo(v("Operador de Caixa"), CFG)
    assert analise.eh_alvo(v("Analista de Fluxo de Caixa Jr"), CFG)
    assert analise.eh_alvo(v("Analista Plan Estoque JR"), CFG)
    assert analise.eh_alvo(gupy._to_vaga(job(2, "Estágio em Liderança e Processos")), CFG)


def test_datas_numericas_e_json_publico(tmp_path):
    import json
    from datetime import datetime
    from bot.registro import br_para_iso
    from bot.site import gerar_site
    assert br_para_iso(46343) == "2026-11-17" and br_para_iso("46343") == "2026-11-17"
    assert br_para_iso("20/11/2026") == "2026-11-20" and br_para_iso("não divulgado") == "não divulgado"
    L = [{"ID": "a", "Nota": 80, "Status": "candidatura enviada", "Vaga": "x", "Data da descoberta": 46343,
          "Prazo": 46346, "Verificação": "aberta"},
         {"ID": "b", "Nota": 70, "Status": "descartada", "Vaga": "y", "Verificação": "aberta"}]
    gerar_site(L, [], [], datetime(2026, 11, 18), str(tmp_path / "index.html"))
    d = json.loads((tmp_path / "vagas.json").read_text(encoding="utf-8"))
    assert [v["id"] for v in d["vagas"]] == ["a"]
    v = d["vagas"][0]
    assert v["status"] == "" and v["descoberta"] == "2026-11-17" and v["prazo"] == "2026-11-20"


def test_dados_neutros_no_json(tmp_path):
    import json
    from datetime import datetime
    from bot.site import gerar_site
    v = gupy._to_vaga(job(77, "Assistente de Planejamento e Qualidade", tipo="vacancy_type_effective", desc=(
        "Cursando Engenharia de Produção ou Mecânica. Formatura entre 2027 e 2028. 40 horas semanais. "
        "Indicadores em Power BI, apoio à qualidade e melhoria contínua. Ensino superior completo desejável.")))
    analise.pontuar(v, CFG, HOJE)
    assert v.horas_semana == 40 and v.curso_categoria == "amplo" and v.formatura_exigida == "2027-2028"
    assert {"Dados e BI", "Qualidade", "Planejamento e projetos", "Processos e melhoria contínua"} <= set(v.areas)
    assert all("2028" not in a or "Pede formatura" in a for a in v.alertas_gerais)   # nada do perfil da Nu
    assert not any("dez/2028" in a for a in v.alertas_gerais)
    linha = registro.vaga_para_linha(v, "2026-11-17")
    linha["Status"] = "nova"
    gerar_site([linha], [], [], datetime(2026, 11, 18), str(tmp_path / "index.html"))
    d = json.loads((tmp_path / "vagas.json").read_text(encoding="utf-8"))["vagas"][0]
    assert d["horas_semana"] == 40 and d["curso_categoria"] == "amplo" and d["formatura_exigida"] == "2027-2028"
    assert "Qualidade" in d["areas"] and d["trecho"].startswith("Cursando Engenharia")
    assert any("CLT" in a for a in d["alertas_gerais"]) and d["pts_aprendizado"] >= 4
    assert d["nota"] == v.nota


def test_emprego_so_entra_com_area_no_titulo():
    cfg = CFG
    assert not analise.emprego_na_area("Assistente de Churrasqueiro", cfg)
    assert not analise.emprego_na_area("Assistente de Loja", cfg)
    assert analise.emprego_na_area("Assistente Administrativo", cfg)
    assert analise.emprego_na_area("Analista Jr de Planejamento", cfg)
    assert analise.emprego_na_area("Trainee 2027", cfg)
    assert not analise.emprego_na_area("Processo Seletivo 2027", cfg)


def test_processo_seletivo_nao_vale_nota_maxima():
    v = analise.pontuar(Vaga(id="t:1", fonte="t", titulo="Estágio - Processo Seletivo 2027", empresa="X",
                             cidade="Campinas", descricao=""), CFG, HOJE)
    assert "Atividades 8/30" in v.detalhe_nota


def test_emprego_fora_da_area_nao_e_alvo_mas_estagio_sim():
    churras = Vaga(id="t:2", fonte="t", titulo="Assistente de Churrasqueiro", empresa="X", cidade="Campinas")
    estagio = Vaga(id="t:3", fonte="t", titulo="Estágio em Loja", empresa="X", cidade="Campinas")
    assert not analise.eh_alvo(churras, CFG)
    assert analise.eh_alvo(estagio, CFG)


def test_detalhe_da_nota_vai_para_o_json():
    from bot.site import _detalhe
    d = _detalhe("Atividades 22/30 (título: dados (muito alta)) | Curso 13/25 (DESCONHECIDO: curso não especificado) | Local 20/20 (Campinas)")
    assert d[0] == {"criterio": "Atividades", "pontos": 22, "max": 30, "motivo": "título: dados (muito alta)"}
    assert [x["criterio"] for x in d] == ["Atividades", "Curso", "Local"]
    assert _detalhe("") == []


def test_trecho_cursos_guarda_a_lista_inteira():
    from bot.text import norm
    d = norm("Requisitos: cursando Engenharia Agrícola, Mecânica, Elétrica ou Produção, com formatura em 2027. Benefícios: VR.")
    t = analise.trecho_cursos(d)
    assert "mecanica" in t and "producao" in t
    assert analise.trecho_cursos(norm("Vaga legal em Campinas.")) == ""


def test_alertas_email_viram_vagas_e_passam_pelos_filtros():
    from bot.main import na_regiao_ou_remota
    from bot.sources.alertas_email import vagas_das_linhas
    linhas = [
        {"ID": "glassdoor:1010333414737", "Fonte": "Glassdoor", "Vaga": "Estágio em Projetos", "Empresa": "MITRATECH LTDA",
         "Cidade": "Campinas", "Link": "https://www.glassdoor.com.br/partner/jobListing.htm?jobListingId=1010333414737", "Recebido em": "2026-11-24"},
        {"ID": "glassdoor:1", "Fonte": "Glassdoor", "Vaga": "Operador de Empilhadeira", "Empresa": "X",
         "Cidade": "Cajamar", "Link": "https://x", "Recebido em": "2026-11-24"},
        {"ID": "indeed:old", "Fonte": "Indeed", "Vaga": "Estágio antigo", "Empresa": "Y",
         "Cidade": "Campinas", "Link": "https://y", "Recebido em": "2026-09-01"},
        {"ID": "", "Vaga": "sem id", "Link": "https://z"},
    ]
    vs = vagas_das_linhas(linhas, HOJE)
    assert [v.id for v in vs] == ["email:glassdoor:1010333414737", "email:glassdoor:1"]
    assert vs[0].fonte == "Glassdoor (e-mail)" and "não confirmada" in vs[0].verificacao
    assert na_regiao_ou_remota(vs[0], CFG) and not na_regiao_ou_remota(vs[1], CFG)
    assert analise.eh_alvo(vs[0], CFG)


def test_bosch_e_cursos_de_outras_areas_nunca_entram():
    bosch = Vaga(id="t:b", fonte="t", titulo="VAGA AFIRMATIVA PcD - ESTÁGIO SUPERIOR - ADMINISTRATIVO", empresa="Bosch", cidade="Campinas")
    odonto = Vaga(id="t:o", fonte="t", titulo="ESTÁGIO EM ODONTOLOGIA - Sem experiência", empresa="Jobbol", cidade="Campinas")
    ok = Vaga(id="t:k", fonte="t", titulo="Estágio em Qualidade", empresa="GE Vernova", cidade="Campinas")
    assert not analise.eh_alvo(bosch, CFG) and not analise.eh_alvo(odonto, CFG) and analise.eh_alvo(ok, CFG)


def test_vaga_do_email_sempre_vai_no_telegram():
    from bot.alertas import montar_texto
    r = {"Nota": 49, "Tipo": "Estágio", "Empresa": "GE Vernova", "Vaga": "Estágio em Qualidade", "Link": "https://x",
         "Cidade": "Campinas", "Modalidade": "", "Carga horária": "", "Publicação": "", "Prazo": "", "Alertas": "",
         "Verificação": "alerta por e-mail (Glassdoor), não confirmada"}
    t = montar_texto([r], [], [], 60, "24/11/2026")
    assert t and "GE Vernova" in t and "do seu e-mail" in t


def test_sao_paulo_so_hibrido_de_empresa_grande_ou_programa():
    from bot.main import na_regiao_ou_remota
    V_ = lambda **k: Vaga(**{"id": "t:x", "fonte": "t", "titulo": "Estágio", "empresa": "X", **k})  # noqa: E731
    assert na_regiao_ou_remota(V_(empresa="Itaú Unibanco", cidade="São Paulo", modalidade="híbrido"), CFG)
    assert not na_regiao_ou_remota(V_(empresa="Itaú Unibanco", cidade="São Paulo", modalidade="presencial"), CFG)
    assert na_regiao_ou_remota(V_(empresa="Itaú Unibanco", cidade="São Paulo", modalidade=""), CFG)
    assert not na_regiao_ou_remota(V_(empresa="Loja do Zé", cidade="São Paulo", modalidade="híbrido"), CFG)
    assert na_regiao_ou_remota(V_(titulo="Programa de Estágio 2027", empresa="Loja do Zé", cidade="São Paulo", modalidade="híbrido"), CFG)
    assert na_regiao_ou_remota(V_(titulo="Programa de Estágio Corporativo", empresa="Itaú Unibanco", cidade=""), CFG)
    assert not na_regiao_ou_remota(V_(empresa="Loja do Zé", cidade=""), CFG)
    assert not na_regiao_ou_remota(V_(empresa="Itaú", cidade="Rio de Janeiro", modalidade="híbrido"), CFG)
    v = analise.pontuar(V_(empresa="Itaú", cidade="São Paulo", modalidade="híbrido"), CFG, HOJE)
    assert "Local 11/20" in v.detalhe_nota
