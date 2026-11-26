"""Extração de informações do texto da vaga e nota de compatibilidade (0-100).

Rubrica (definida por Nu):
  30 atividades x experiências/interesses
  25 elegibilidade do curso e requisitos acadêmicos
  20 localização e modalidade
  15 jornada
  10 aprendizado e desenvolvimento
Critério não informado = "desconhecido": recebe pontuação intermediária e isso
fica escrito no detalhe da nota. Requisitos obrigatórios não atendidos viram
ALERTAS, independentemente da nota.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from .models import Vaga
from .text import contains_any, norm


# ----------------------------------------------------------------- extração

def extrair_carga(desc_n: str) -> tuple[str, int | None]:
    """Retorna (texto para planilha, horas semanais estimadas ou None)."""
    m = re.search(r"(\d{2})\s*(?:h|hrs?|horas|hours)\s*(?:semanais|por semana|/\s*semana|semana|per week|a week|/\s*week|weekly)", desc_n)
    if m:
        h = int(m.group(1))
        return f"{h}h/semana", h
    m = re.search(r"(\d)\s*(?:h|hrs?|horas|hours)\s*(?:diarias|por dia|/\s*dia|dia|per day|a day|/\s*day|daily)", desc_n)
    if m:
        h = int(m.group(1))
        return f"{h}h/dia", h * 5
    m = re.search(r"(?:jornada|carga horaria|horario)[^.\n]{0,40}?(\d{1,2})\s*(?:h|horas)", desc_n)
    if m:
        h = int(m.group(1))
        return (f"{h}h/semana", h) if h >= 15 else (f"{h}h/dia", h * 5)
    return "não informada", None


# Reference (Companhia de Estágios, 2026): Southeast average R$ 2.009 for 30h/week. Big programs
# published this season paid R$ 2.000 to 3.300 (Embraer 2.000, Boticário 2.300, Samsung 2.500, Blip 3.300).
FAIXA_GRANDE = (2200, 3000)
FAIXA_OUTRAS = (1500, 2100)
TECH = ["dados", "data", "analytics", "tecnologia", "software", "ti ", "sistemas", "inteligencia artificial",
        " ia ", "desenvolvimento", "engenharia de dados", "machine learning", "produto"]


def _reais(x: float) -> str:
    return f"{int(round(x / 100.0) * 100):,}".replace(",", ".")


def bolsa_publicada(desc: str) -> int | None:
    """Value in R$ written near 'bolsa'/'remuneração'/'salário' (first plausible one)."""
    for m in re.finditer(r"(?i)(bolsa|remunera|sal[aá]rio)[^\n]{0,50}?R\$\s?([\d\.]+)(?:,\d{2})?", desc or ""):
        try:
            valor = int(m.group(2).replace(".", ""))
        except ValueError:
            continue
        if 500 <= valor <= 15000:
            return valor
    return None


def estimar_bolsa(v: Vaga, grande: bool, eh_estagio: bool) -> str:
    """Published value when there is one; otherwise a rough range for internships."""
    pub = bolsa_publicada(v.descricao)
    if pub:
        return f"R$ {_reais(pub)} (publicada)"
    if not eh_estagio:
        return ""
    lo, hi = FAIXA_GRANDE if grande else FAIXA_OUTRAS
    texto = f" {norm(v.titulo)} {norm(v.descricao[:600])} "
    if any(t in texto for t in TECH):
        lo, hi = lo + 300, hi + 300
    if norm(v.cidade).startswith("sao paulo"):
        lo, hi = lo + 200, hi + 200
    if v.horas_semana and v.horas_semana < 30:
        f = v.horas_semana / 30
        lo, hi = lo * f, hi * f
    return f"R$ {_reais(lo)} a {_reais(hi)} (estimativa)"


def extrair_bolsa(desc: str) -> str:
    achados = []
    m = re.search(r"(?i)(bolsa[^\n]{0,40}?R\$\s?[\d\.]+(?:,\d{2})?|R\$\s?[\d\.]+(?:,\d{2})?[^\n]{0,15}bolsa)", desc)
    if m:
        achados.append(m.group(0).strip())
    beneficios = ["vale-refeição", "vale refeição", "vale-alimentação", "vale alimentação", "VR", "VA",
                  "vale-transporte", "vale transporte", "fretado", "assistência médica", "plano de saúde",
                  "seguro de vida", "Gympass", "Wellhub", "restaurante", "refeitório", "auxílio"]
    dn = norm(desc)
    bens = [b for b in beneficios if re.search(rf"(?<![a-z]){re.escape(norm(b))}(?![a-z])", dn)]
    if bens:
        achados.append("benefícios citados: " + ", ".join(dict.fromkeys(bens)))
    return " | ".join(achados) if achados else "não publicado"


CURSO_EXPLICITO = ["engenharia agricola", "eng. agricola", "eng agricola", "agricultural engineering"]
CURSO_AMPLO = ["engenharias", "todas as engenharias", "qualquer engenharia", "engenharia (todas",
               "cursos de engenharia", "engenharia em geral", "engenharia ou areas afins",
               "engineering"]
CURSO_ABERTO = ["todos os cursos", "qualquer curso", "qualquer area de formacao", "todas as areas",
                "exatas", "areas correlatas", "cursos correlatos", "areas afins", "stem"]


FLEXIVEL = ["horario flexivel", "horarios flexiveis", "flexibilidade de horario", "flexibilidade de horarios",
            "jornada flexivel", "carga horaria flexivel", "horario a combinar", "voce monta seu horario",
            "flexible hours", "flexible schedule"]
TETO_SEM_ENGENHARIA = 79


def extrair_cursos(desc_n: str) -> tuple[str, str]:
    """(texto para planilha, categoria: explicito|amplo|aberto|lista|desconhecido)."""
    if contains_any(desc_n, CURSO_EXPLICITO):
        return "Engenharia Agrícola citada", "explicito"
    if contains_any(desc_n, CURSO_AMPLO):
        return "Engenharias em geral", "amplo"
    sem_areas = re.sub(r"engenharia de (dados|prompt|machine learning|ia)|engenheir[oa] de dados", " ", desc_n)
    if re.search(r"\beng(?:enharias?\b|\.\s)", sem_areas):  # "Engenharia de Produção", "Eng. de Controle"...
        return "Engenharia citada entre os cursos", "amplo"
    if contains_any(desc_n, CURSO_ABERTO):
        return "Cursos abertos/exatas/afins", "aberto"
    trechos = [m.group(1).strip() for m in
               re.finditer(r"(?:cursando|graduacao em|formacao em|estudantes de|cursos?:?)\s+([^\n.;]{5,160})", desc_n)]
    for trecho in trechos:  # any course list that names engineering counts
        if "engenharia" in trecho or "engineering" in trecho:
            return f"Engenharia (lista: {trecho[:100]})", "amplo"
    if trechos:
        return f"Lista sem Eng. Agrícola: {trechos[0][:100]}", "lista"
    return "não especificado", "desconhecido"


_CURSO_GATILHO = re.compile(r"(?<![a-z])(cursando|graduacao|graduando|formacao|estudantes? de|bacharelado|"
                            r"tecnologo|cursos?|engenharias?|eng\.)(?![a-z])")


def trecho_cursos(desc_n: str, limite: int = 400) -> str:
    """Pieces of the description that talk about accepted courses (for matching anyone's course).

    The sheet's 'Cursos aceitos' says only "Engenharia Agrícola citada" when Nu's course appears,
    which hides the rest of the list; this keeps the original wording around each mention.
    """
    pedacos, fim_anterior = [], -1
    for m in _CURSO_GATILHO.finditer(desc_n):
        ini, fim = max(0, m.start() - 20, fim_anterior), min(len(desc_n), m.end() + 160)
        if ini < fim:
            pedacos.append(desc_n[ini:fim].strip())
            fim_anterior = fim
        if sum(len(p) for p in pedacos) >= limite:
            break
    return " … ".join(pedacos)[:limite]


def extrair_ano_formatura(desc_n: str) -> tuple[int, int] | None:
    """Procura exigência do tipo 'formatura até dez/2027' ou 'conclusão entre 2026 e 2027'.
    Retorna (ano_min, ano_max) ou None."""
    m = re.search(r"(?:formatura|conclusao|formacao|graduacao)[^\n]{0,60}?(20[2-3]\d)"
                  r"(?:[^\n]{0,20}?(?:e|a|ate|-)\s*[^\n]{0,15}?(20[2-3]\d))?", desc_n)
    if not m:
        return None
    a = int(m.group(1))
    b = int(m.group(2)) if m.group(2) else a
    return min(a, b), max(a, b)


# Taxonomia neutra de áreas (para nota pessoal de qualquer usuário)
AREAS_AMIGAVEIS = {
    "Dados e BI": ["dados", "analytics", "bi", "power bi", "business intelligence", "data analyst", "data science",
                   "ciencia de dados", "dashboard", "indicadores", "kpi"],
    "Processos e melhoria contínua": ["processo", "melhoria continua", "lean", "excelencia operacional", "kaizen",
                                      "six sigma"],
    "Planejamento e projetos": ["planejamento", "pmo", "projeto", "controle de projetos", "pcp", "project"],
    "Operações": ["operacoes", "operations", "operacional", "producao"],
    "Agro": ["agricola", "agronegocio", "agro", "agricultura", "agronomia", "agricultura de precisao", "campo"],
    "Sustentabilidade e meio ambiente": ["sustentabilidade", "meio ambiente", "ambiental", "esg", "sustainability"],
    "Saúde e segurança (EHS)": ["ehs", "sso", "saude e seguranca", "seguranca do trabalho", "hse"],
    "Supply chain e logística": ["supply", "supply chain", "logistica", "compras", "suprimentos", "procurement",
                                 "estoque"],
    "Qualidade": ["qualidade", "quality"],
    "Finanças e controladoria": ["financeiro", "financas", "controladoria", "custos", "contabil", "fiscal",
                                 "tesouraria", "faturamento"],
    "P&D e pesquisa": ["p&d", "pesquisa", "research", "desenvolvimento de produto", "laboratorio"],
    "Engenharia, automação e manutenção": ["automacao", "manutencao", "eletrica", "mecanica", "engenharia",
                                           "projetos mecanicos"],
    "TI e software": ["ti", "software", "desenvolvedor", "desenvolvimento de sistemas", "programacao", "sistemas"],
    "Administrativo e RH": ["administrativo", "administracao", "rh", "recursos humanos", "departamento pessoal"],
}


def areas_da_vaga(titulo_n: str, desc_n: str) -> list[str]:
    texto = f"{titulo_n} {titulo_n} {desc_n[:4000]}"
    return [nome for nome, termos in AREAS_AMIGAVEIS.items() if contains_any(texto, termos)]


# ------------------------------------------------------------------ nota

def _cidade_norm(c: str) -> str:
    return norm(c.split(",")[0].split("-")[0])


# Phrases that contain area words but say nothing about the work ("Processo Seletivo 2027").
_FRASES_VAZIAS = re.compile(r"(?<![a-z])(processos? seletivos?|programa de estagio|projeto de estagio|programa de trainee)(?![a-z])")


def sem_frases_vazias(texto_norm: str) -> str:
    return _FRASES_VAZIAS.sub(" ", texto_norm)


def pontuar(v: Vaga, cfg: dict, hoje: date | None = None) -> Vaga:
    hoje = hoje or date.today()
    areas = cfg["areas"]
    titulo_n = norm(v.titulo)
    desc_n = norm(v.descricao)
    # area matching ignores "processo seletivo" & co., otherwise any program title scores 30/30
    titulo_area = sem_frases_vazias(titulo_n)
    desc_area = sem_frases_vazias(desc_n)
    detalhes: list[str] = []
    alertas: list[str] = []

    # --- 1. Atividades (30)
    tiers = [("muito_alta", 30, 18), ("alta", 25, 14), ("media", 19, 10)]
    p_ativ, motivo = 8, "nenhuma área-alvo identificada"
    for nome, no_titulo, so_desc in tiers:
        hits_t = contains_any(titulo_area, areas[nome])
        if hits_t:
            p_ativ, motivo = no_titulo, f"título: {', '.join(hits_t[:3])} ({nome.replace('_', ' ')})"
            break
    if p_ativ == 8:
        for nome, no_titulo, so_desc in tiers:
            hits_d = contains_any(desc_area, areas[nome])
            if len(hits_d) >= 2:
                p_ativ, motivo = so_desc, f"descrição: {', '.join(hits_d[:3])} ({nome.replace('_', ' ')})"
                break
    # programs of big companies pick the area later (tracks/rotation): not knowing it is not a minus
    grande_ou_programa = empresa_grande(v, cfg) or "programa de estagio" in titulo_n
    if p_ativ == 8 and grande_ou_programa:
        p_ativ, motivo = 18, "programa/empresa grande: área escolhida depois (trilhas)"
    # bônus por ferramentas que Nu domina
    ferramentas = contains_any(desc_n, ["excel", "power bi", "python", "sql", "power query", "dashboards"])
    if ferramentas and p_ativ < 30:
        p_ativ = min(30, p_ativ + 2 * len(ferramentas))
        motivo += f"; ferramentas: {', '.join(ferramentas)}"
    fora = contains_any(titulo_n, cfg.get("areas_fora_do_perfil", []))
    if fora:
        p_ativ = min(p_ativ, 6)
        motivo += f"; área fora do perfil no título ({', '.join(fora)})"
    detalhes.append(f"Atividades {p_ativ}/30 ({motivo})")

    # --- 2. Curso (25)
    v.cursos_aceitos, cat = extrair_cursos(desc_n)
    v.curso_categoria = cat
    v.trecho_cursos = trecho_cursos(desc_n)
    gerais: list[str] = []
    p_curso = {"explicito": 25, "amplo": 22, "aberto": 19, "lista": 4, "desconhecido": 13}[cat]
    nota_curso = {"desconhecido": "DESCONHECIDO: curso não especificado, nota intermediária"}.get(cat, v.cursos_aceitos)
    if cat == "lista":
        alertas.append("Curso: lista publicada não inclui Eng. Agrícola/Engenharias. Confirmar antes de aplicar.")
        gerais.append("A lista de cursos publicada não inclui engenharias: confira se o seu curso é aceito.")
    if re.search(r"(?<![a-z])(ensino medio|nivel tecnico|curso tecnico|estagio tecnico)(?![a-z])", titulo_n + " " + desc_n[:600]):
        p_curso = min(p_curso, 3)
        alertas.append("Possível vaga de nível técnico/médio, não superior.")
        gerais.append("Possível vaga de nível técnico/médio, não superior.")
    forma = extrair_ano_formatura(desc_n)
    ano_nu = int(cfg["perfil"]["formatura"][:4])
    if forma:
        amin, amax = forma
        v.formatura_exigida = f"{amin}-{amax}"
        gerais.append(f"Pede formatura entre {amin} e {amax}." if amin != amax else f"Pede formatura em {amin}.")
        if ano_nu > amax:
            p_curso = max(0, p_curso - 12)
            alertas.append(f"Exige formatura até {amax}; a formatura de Nu está prevista para {cfg['perfil']['formatura']}.")
        elif ano_nu < amin:
            alertas.append(f"Pede formatura a partir de {amin}; confirmar elegibilidade.")
        else:
            nota_curso += f"; formatura {amin}-{amax} compatível"
    detalhes.append(f"Curso {p_curso}/25 ({nota_curso})")

    # --- 3. Localização e modalidade (20)
    loc = cfg["localizacao"]
    p1 = {norm(c) for c in loc["prioridade_1"]}
    p2 = {norm(c) for c in loc["prioridade_2"]}
    c = _cidade_norm(v.cidade)
    mod = v.modalidade
    if "barao geraldo" in desc_n or "barao geraldo" in norm(v.cidade):
        c = "campinas"
    grande = grande_ou_programa
    hib_ok = {norm(x) for x in loc.get("hibrido_ok", [])}
    if c in p1:
        p_loc, m_loc = (20, f"{v.cidade} (prioridade 1), {mod or 'modalidade não informada'}")
    elif mod == "remoto":
        # 100% remote is as good as Campinas for Nu
        p_loc, m_loc = (20, "remoto")
    elif c in p2:
        p_loc, m_loc = (16, f"{v.cidade} (prioridade 2), {mod or 'modalidade não informada'}")
    elif c in hib_ok and mod == "híbrido":
        p_loc, m_loc = ((17, f"{v.cidade} híbrido, empresa grande/programa") if grande else (11, f"{v.cidade} híbrido"))
        alertas.append(f"Híbrido em {v.cidade}: confirme quantos dias são presenciais.")
    elif c in hib_ok:
        p_loc, m_loc = ((14, f"{v.cidade}, empresa grande/programa, modalidade não informada") if grande
                        else (7, f"{v.cidade}, modalidade não informada"))
        alertas.append(f"{v.cidade}: só serve se for híbrido ou remoto. Confirme o modelo antes de se candidatar.")
    elif not c:
        p_loc, m_loc = ((14, "empresa grande, cidade não informada") if grande else (8, "DESCONHECIDO: cidade não informada"))
    elif mod == "híbrido":
        p_loc, m_loc = (5, f"{v.cidade} híbrido: deslocamento NÃO verificado")
        alertas.append(f"Híbrido em {v.cidade}: verificar frequência presencial e deslocamento.")
    else:
        p_loc, m_loc = (0, f"{v.cidade}, {mod or 'modalidade não informada'}: fora da região")
    detalhes.append(f"Local {p_loc}/20 ({m_loc})")

    # --- 4. Jornada (15)
    v.carga_horaria, horas = extrair_carga(desc_n)
    v.horas_semana = horas
    eh_estagio = tipo_vaga(v) in ("Estágio", "Programa de estágio")
    if horas is None and eh_estagio:
        # Lei 11.788/2008, art. 10: estágio de ensino superior tem no máximo 6 h/dia e 30 h/semana
        p_jor, m_jor = 15, "estágio: por lei até 30h semanais"
    elif horas is None:
        p_jor, m_jor = 8, "DESCONHECIDA: jornada não publicada, nota intermediária"
    elif horas <= 30:
        p_jor, m_jor = 15, v.carga_horaria
    elif horas <= 35:
        p_jor, m_jor = 9, v.carga_horaria
    else:
        p_jor, m_jor = 3, f"{v.carga_horaria} (acima de 30h)"
        alertas.append(f"Jornada {v.carga_horaria}: acima das 30h semanais preferidas.")
        gerais.append(f"Jornada de {v.carga_horaria}.")
    detalhes.append(f"Jornada {p_jor}/15 ({m_jor})")

    # --- 5. Aprendizado (10)
    sinais = contains_any(desc_n, ["programa de estagio", "mentoria", "mentor", "treinamento", "trilha",
                                    "capacitacao", "desenvolvimento profissional", "job rotation",
                                    "efetivacao", "projeto de estagio", "aprendizado", "rotacao"])
    p_apr = min(10, 4 + 2 * len(sinais)) if sinais else 4
    if grande:
        # big companies and internship programs come with structured training
        sinais = ["empresa grande/programa", *sinais]
        p_apr = 10
    v.pts_aprendizado = p_apr
    detalhes.append(f"Aprendizado {p_apr}/10 ({', '.join(sinais[:4]) if sinais else 'sem sinais explícitos'})")

    # --- Prioridade (bônus): what Nu marked as 100% of her interest
    bonus, porque = 0, []
    if grande_ou_programa:
        bonus, porque = bonus + 5, porque + ["empresa grande/programa"]
    if mod == "remoto":
        bonus, porque = bonus + 5, porque + ["100% remoto"]
    flexivel = contains_any(desc_n, FLEXIVEL)
    if flexivel:
        bonus, porque = bonus + 2, porque + ["horário flexível"]
    if bonus:
        detalhes.append(f"Prioridade +{bonus} ({', '.join(porque)})")

    v.nota = min(100, p_ativ + p_curso + p_loc + p_jor + p_apr + bonus)
    # Nu's priority: remote internships that accept engineering, best if hours are flexible.
    # Jobs that don't cite engineering are not a priority: they stay below every job that does.
    cita_eng = cat in ("explicito", "amplo")
    if mod == "remoto" and eh_estagio and cita_eng:
        piso = 95 if flexivel else 90
        if v.nota < piso:
            detalhes.append(f"Piso de estágio remoto que aceita engenharia{' e é flexível' if flexivel else ''}: {piso}")
            v.nota = piso
    if not cita_eng and v.nota > TETO_SEM_ENGENHARIA:
        detalhes.append(f"Não cita engenharia: nota limitada a {TETO_SEM_ENGENHARIA}")
        v.nota = TETO_SEM_ENGENHARIA
    v.detalhe_nota = " | ".join(detalhes)

    # --- outros dados
    v.bolsa_beneficios = extrair_bolsa(v.descricao)
    v.bolsa_estimada = estimar_bolsa(v, grande_ou_programa, eh_estagio)
    if v.prazo:
        try:
            if datetime.strptime(v.prazo, "%Y-%m-%d").date() < hoje:
                alertas.append(f"Prazo de inscrição ({v.prazo}) já passou.")
                gerais.append("O prazo de inscrição informado já passou.")
        except ValueError:
            pass
    if v.publicada_em:
        try:
            dias = (hoje - datetime.strptime(v.publicada_em, "%Y-%m-%d").date()).days
            v.recente = dias <= cfg["busca"].get("recente_dias", 7)
        except ValueError:
            pass
    if tipo_vaga(v) in ("Emprego", "Trainee"):
        alertas.append("Emprego/CLT: confirmar compatibilidade com o horário das aulas (formatura dez/2028).")
        gerais.append("Emprego CLT: confira se o horário é compatível com as aulas.")
        if re.search(r"superior completo|graduacao completa|formad[oa]s?\b|ensino superior concluido", desc_n):
            alertas.append("Pode exigir graduação completa.")
            gerais.append("Pode exigir graduação completa.")
    v.areas = areas_da_vaga(titulo_n, desc_n)
    v.alertas_gerais = gerais
    v.alertas = alertas
    return v


def dentro_da_janela(v: Vaga, cfg: dict, hoje: date | None = None) -> bool:
    """Sem data publicada => mantém (não dá para afirmar que é antiga).
    Gupy only lists jobs with applications open, so an old publication date doesn't mean closed:
    the window doesn't apply to it (it hid 23 open remote internships)."""
    if not v.publicada_em or v.fonte in ("gupy", "eureca", "99jobs", "ciadetalentos"):
        return True
    hoje = hoje or date.today()
    try:
        d = datetime.strptime(v.publicada_em, "%Y-%m-%d").date()
    except ValueError:
        return True
    return (hoje - d).days <= cfg["busca"].get("janela_dias", 30)


def tipo_vaga(v: Vaga) -> str:
    t = norm(v.titulo)
    if v.fonte == "google_alertas":
        return "Programa de estágio"
    if eh_estagio(v):
        return "Estágio"
    if "trainee" in t:
        return "Trainee"
    if v.tipo == "bolsa":
        return "Bolsa"
    return "Emprego"


def titulo_excluido(titulo: str, cfg: dict) -> bool:
    """True se o título tem algum termo de busca.excluir_titulos (palavra inteira)."""
    t = norm(titulo)
    termos = [x.strip() for x in cfg.get("busca", {}).get("excluir_titulos", [])]
    return bool(contains_any(t, termos))


def emprego_na_area(titulo: str, cfg: dict) -> bool:
    """A job (not internship) only counts if its title names one of Nu's areas.

    The Gupy search for "assistente" returns every kind of assistant (barbecue, shop, kitchen...);
    a blocklist never ends, so jobs need a positive match instead.
    """
    t = sem_frases_vazias(norm(titulo))
    if contains_any(t, ["trainee"]):
        return True
    a = cfg.get("areas", {})
    termos = [*a.get("muito_alta", []), *a.get("alta", []), *a.get("media", []),
              *cfg.get("busca", {}).get("emprego_titulo_tambem_aceita", [])]
    return bool(contains_any(t, termos))


def empresa_grande(v: Vaga, cfg: dict) -> bool:
    return bool(contains_any(norm(f" {v.empresa} {v.titulo} "), cfg.get("empresas_grandes", [])))


def eh_alvo(v: Vaga, cfg: dict) -> bool:
    """Estágio sempre; emprego só se incluir_empregos, cargo de entrada e título da área."""
    b = cfg.get("busca", {})
    if titulo_excluido(v.titulo, cfg):
        return False
    if contains_any(norm(f"{v.empresa} {v.titulo}"), b.get("excluir_empresas", [])):
        return False
    if "apprentice" in (v.tipo or "").lower():
        return False
    if eh_estagio(v):
        return True
    if v.tipo == "bolsa":
        return False
    return bool(b.get("incluir_empregos")) and emprego_na_area(v.titulo, cfg)


def eh_estagio(v: Vaga) -> bool:
    t = norm(v.titulo)
    return ("internship" in (v.tipo or "").lower() or v.tipo == "bolsa"
            or bool(re.search(r"estagi|(?<![a-z])intern(ship)?s?(?![a-z])", t)))
