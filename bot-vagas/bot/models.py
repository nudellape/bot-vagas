"""Estrutura comum de uma vaga, independente da fonte."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Vaga:
    id: str                      # chave única: "<fonte>:<id na fonte>"
    fonte: str                   # gupy | workday
    empresa: str
    titulo: str
    cidade: str = ""
    estado: str = ""
    modalidade: str = ""         # presencial | híbrido | remoto | "" (não informado)
    descricao: str = ""          # texto puro
    publicada_em: str = ""       # AAAA-MM-DD, somente se a fonte informar
    prazo: str = ""              # AAAA-MM-DD, somente se a fonte informar
    link: str = ""
    tipo: str = ""               # tipo informado pela fonte (ex.: vacancy_type_internship, bolsa)
    verificacao: str = ""        # texto próprio de verificação (fontes que não confirmam abertura)

    # Preenchidos pela análise
    carga_horaria: str = "não informada"
    cursos_aceitos: str = "não especificado"
    bolsa_beneficios: str = "não publicado"
    nota: int = 0
    detalhe_nota: str = ""
    alertas: list[str] = field(default_factory=list)
    recente: bool = False
    # dados neutros (sem nada do perfil de Nu), para outros apps calcularem nota pessoal
    horas_semana: int | None = None
    curso_categoria: str = ""        # explicito | amplo | aberto | lista | desconhecido
    formatura_exigida: str = ""      # "2027-2028" ou ""
    areas: list[str] = field(default_factory=list)
    alertas_gerais: list[str] = field(default_factory=list)
    pts_aprendizado: int = 0
    trecho_cursos: str = ""      # trechos da descrição que falam de cursos aceitos
