"""Extração de informações do texto da vaga e nota de compatibilidade (0-100).

Rubrica (definida pela Nu):
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


def extrair_cursos(desc_n: str) -> tuple[str, str]:
    """(texto para planilha, categoria: explicito|amplo|aberto|lista|desconhecido)."""
    if contains_any(desc_n, CURSO_EXPLICITO):
        return "Engenharia Agrícola citada", "explicito"
    if contains_any(desc_n, CURSO_AMPLO):
        return "Engenharias em geral", "amplo"
    if contains_any(desc_n, CURSO_ABERTO):
        return "Cursos abertos/exatas/afins", "aberto"
    m = re.search(r"(?:cursando|graduacao em|formacao em|estudantes de|cursos?:?)\s+([^\n.;]{5,160})", desc_n)
    if m:
        trecho = m.group(1).strip()
        if "engenharia" in trecho:
            return f"Engenharia (lista: {trecho[:100]})", "amplo"
        return f"Lista sem Eng. Agrícola: {trecho[:100]}", "lista"
    return "não especificado", "desconhecido"


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


# ------------------------------------------------------------------ nota

def _cidade_norm(c: str) -> str:
    return norm(c.split(",")[0].split("-")[0])


def pontuar(v: Vaga, cfg: dict, hoje: date | None = None) -> Vaga:
    hoje = hoje or date.today()
    areas = cfg["areas"]
    titulo_n = norm(v.titulo)
    desc_n = norm(v.descricao)
    detalhes: list[str] = []
    alertas: list[str] = []

    # --- 1. Atividades (30)
    tiers = [("muito_alta", 30, 18), ("alta", 25, 14), ("media", 19, 10)]
    p_ativ, motivo = 8, "nenhuma área-alvo identificada"
    for nome, no_titulo, so_desc in tiers:
        hits_t = contains_any(titulo_n, areas[nome])
        if hits_t:
            p_ativ, motivo = no_titulo, f"título: {', '.join(hits_t[:3])} ({nome.replace('_', ' ')})"
            break
    if p_ativ == 8:
        for nome, no_titulo, so_desc in tiers:
            hits_d = contains_any(desc_n, areas[nome])
            if len(hits_d) >= 2:
                p_ativ, motivo = so_desc, f"descrição: {', '.join(hits_d[:3])} ({nome.replace('_', ' ')})"
                break
    # bônus por ferramentas que a Nu domina
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
    p_curso = {"explicito": 25, "amplo": 22, "aberto": 19, "lista": 4, "desconhecido": 13}[cat]
    nota_curso = {"desconhecido": "DESCONHECIDO: curso não especificado, nota intermediária"}.get(cat, v.cursos_aceitos)
    if cat == "lista":
        alertas.append("Curso: lista publicada não inclui Eng. Agrícola/Engenharias. Confirmar antes de aplicar.")
    if re.search(r"(?<![a-z])(ensino medio|nivel tecnico|curso tecnico|estagio tecnico)(?![a-z])", titulo_n + " " + desc_n[:600]):
        p_curso = min(p_curso, 3)
        alertas.append("Possível vaga de nível técnico/médio, não superior.")
    forma = extrair_ano_formatura(desc_n)
    ano_nu = int(cfg["perfil"]["formatura"][:4])
    if forma:
        amin, amax = forma
        if ano_nu > amax:
            p_curso = max(0, p_curso - 12)
            alertas.append(f"Exige formatura até {amax}; a previsão da Nu é {cfg['perfil']['formatura']}.")
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
    if c in p1:
        p_loc, m_loc = (20, f"{v.cidade} (prioridade 1), {mod or 'modalidade não informada'}")
    elif c in p2:
        p_loc, m_loc = (16, f"{v.cidade} (prioridade 2), {mod or 'modalidade não informada'}")
    elif mod == "remoto":
        p_loc, m_loc = (15, "remoto")
    elif not c:
        p_loc, m_loc = (8, "DESCONHECIDO: cidade não informada")
    elif mod == "híbrido":
        p_loc, m_loc = (5, f"{v.cidade} híbrido: deslocamento NÃO verificado")
        alertas.append(f"Híbrido em {v.cidade}: verificar frequência presencial e deslocamento.")
    else:
        p_loc, m_loc = (0, f"{v.cidade}, {mod or 'modalidade não informada'}: fora da região")
    detalhes.append(f"Local {p_loc}/20 ({m_loc})")

    # --- 4. Jornada (15)
    v.carga_horaria, horas = extrair_carga(desc_n)
    if horas is None:
        p_jor, m_jor = 8, "DESCONHECIDA: jornada não publicada, nota intermediária"
    elif horas <= 30:
        p_jor, m_jor = 15, v.carga_horaria
    elif horas <= 35:
        p_jor, m_jor = 9, v.carga_horaria
    else:
        p_jor, m_jor = 3, f"{v.carga_horaria} (acima de 30h)"
        alertas.append(f"Jornada {v.carga_horaria}: acima das 30h semanais preferidas.")
    detalhes.append(f"Jornada {p_jor}/15 ({m_jor})")

    # --- 5. Aprendizado (10)
    sinais = contains_any(desc_n, ["programa de estagio", "mentoria", "mentor", "treinamento", "trilha",
                                    "capacitacao", "desenvolvimento profissional", "job rotation",
                                    "efetivacao", "projeto de estagio", "aprendizado", "rotacao"])
    p_apr = min(10, 4 + 2 * len(sinais)) if sinais else 4
    detalhes.append(f"Aprendizado {p_apr}/10 ({', '.join(sinais[:4]) if sinais else 'sem sinais explícitos'})")

    v.nota = p_ativ + p_curso + p_loc + p_jor + p_apr
    v.detalhe_nota = " | ".join(detalhes)

    # --- outros dados
    v.bolsa_beneficios = extrair_bolsa(v.descricao)
    if v.prazo:
        try:
            if datetime.strptime(v.prazo, "%Y-%m-%d").date() < hoje:
                alertas.append(f"Prazo de inscrição ({v.prazo}) já passou.")
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
        if re.search(r"superior completo|graduacao completa|formad[oa]s?\b|ensino superior concluido", desc_n):
            alertas.append("Pode exigir graduação completa.")
    v.alertas = alertas
    return v


def dentro_da_janela(v: Vaga, cfg: dict, hoje: date | None = None) -> bool:
    """Sem data publicada => mantém (não dá para afirmar que é antiga)."""
    if not v.publicada_em:
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


def eh_alvo(v: Vaga, cfg: dict) -> bool:
    """Estágio sempre; emprego só se incluir_empregos e o cargo for de entrada."""
    b = cfg.get("busca", {})
    t = f" {norm(v.titulo)} "
    if any(f" {norm(x).strip()}" in t if x.startswith(" ") else norm(x) in t for x in b.get("excluir_titulos", [])):
        return False
    if "apprentice" in (v.tipo or "").lower():
        return False
    if eh_estagio(v):
        return True
    if v.tipo == "bolsa":
        return False
    return bool(b.get("incluir_empregos"))


def eh_estagio(v: Vaga) -> bool:
    t = norm(v.titulo)
    return ("internship" in (v.tipo or "").lower() or v.tipo == "bolsa"
            or bool(re.search(r"estagi|(?<![a-z])intern(ship)?s?(?![a-z])", t)))
