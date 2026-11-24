"""Fonte: programas de estágio de grandes empresas com site próprio (fora da Gupy),
cadastrados à mão em config.yaml -> programas_destaque. Saem do app quando o prazo passa."""
from __future__ import annotations

import hashlib
from datetime import date

from ..models import Vaga


def coletar(cfg: dict, session=None):
    vagas = []
    hoje = date.today().isoformat()
    for p in cfg.get("programas_destaque") or []:
        prazo = str(p.get("prazo", "") or "")
        if prazo and prazo < hoje:
            continue
        chave = hashlib.sha1(str(p.get("link", "")).encode()).hexdigest()[:12]
        vagas.append(Vaga(
            id=f"programa:{chave}", fonte="programa", empresa=str(p.get("empresa", "")), titulo=str(p.get("titulo", "")),
            cidade=str(p.get("cidade", "") or ""), modalidade=str(p.get("modalidade", "") or ""),
            descricao=str(p.get("descricao", "") or ""), prazo=prazo, link=str(p.get("link", "")),
            tipo="vacancy_type_internship",
            verificacao="programa cadastrado à mão (site da empresa): confira o edital",
        ))
    return vagas, [], set(), {v.id for v in vagas}
