"""Execução completa: coleta -> filtro -> nota -> registro -> alerta.

Uso:
    python -m bot.main                 # execução normal
    python -m bot.main --sem-alerta    # atualiza o registro sem enviar mensagens
    python -m bot.main --relatorio     # imprime o top 10 no terminal
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

from . import alertas, analise, registro
from .models import Vaga
from .sources import agrobase, alertas_google, fapesp, gupy, smartrecruiters, workday
from .text import norm

log = logging.getLogger("bot")
TZ = ZoneInfo("America/Sao_Paulo")


def carregar_config(caminho: str | None = None) -> dict:
    caminho = caminho or os.getenv("CONFIG_PATH") or str(Path(__file__).resolve().parent.parent / "config.yaml")
    with open(caminho, encoding="utf-8") as f:
        return yaml.safe_load(f)


def na_regiao_ou_remota(v: Vaga, cfg: dict) -> bool:
    loc = cfg["localizacao"]
    cidades = {norm(c) for c in loc["prioridade_1"] + loc["prioridade_2"]}
    c = norm(v.cidade.split(",")[0].split("-")[0])
    return c in cidades or v.modalidade == "remoto" or "barao geraldo" in norm(v.cidade)


def deduplicar(vagas: list[Vaga]) -> list[Vaga]:
    """Remove repetidas: mesmo ID, ou mesma empresa+título+cidade vinda de outra consulta/fonte."""
    por_id: dict[str, Vaga] = {}
    for v in vagas:
        por_id.setdefault(v.id, v)
    vistos, out = set(), []
    for v in por_id.values():
        chave = (norm(v.empresa), norm(v.titulo), norm(v.cidade))
        if chave in vistos:
            continue
        vistos.add(chave)
        out.append(v)
    return out


def coletar_tudo(cfg: dict, session: requests.Session | None = None):
    s = session or requests.Session()
    erros: list[str] = []
    fontes_ok: set[str] = set()

    v_gupy, e_gupy = gupy.coletar(cfg, s)
    erros += e_gupy
    if not e_gupy:  # só considera a Gupy "completa" se nenhuma consulta falhou
        fontes_ok.add("gupy:")
    extras, extras_ids = [], set()
    for fonte in (workday, smartrecruiters, agrobase, fapesp, alertas_google):
        v, avisos, ok, ids = fonte.coletar(cfg, s)
        extras += v
        extras_ids |= ids
        fontes_ok |= ok
        for a in avisos:  # empresas extras: falha vai só para o log, sem alerta
            log.warning("aviso: %s", a)
    coletar_tudo.ids_extras = extras_ids
    return v_gupy + extras, erros, fontes_ok


def processar(brutas: list[Vaga], cfg: dict, hoje) -> tuple[list[Vaga], set[str]]:
    ids_abertos = {v.id for v in brutas} | getattr(coletar_tudo, "ids_extras", set())
    vagas = [v for v in deduplicar(brutas)
             if analise.eh_alvo(v, cfg) and na_regiao_ou_remota(v, cfg) and analise.dentro_da_janela(v, cfg, hoje)]
    for v in vagas:
        analise.pontuar(v, cfg, hoje)
    return sorted(vagas, key=lambda v: -v.nota), ids_abertos


def imprimir_relatorio(linhas: list[dict], n: int = 10):
    abertas = [r for r in linhas if str(r.get("Verificação", "")).startswith("aberta")
               and r.get("Status") not in ("descartada", "encerrada")]
    print(f"\nTOP {min(n, len(abertas))} VAGAS CONFIRMADAMENTE LISTADAS NA FONTE HOJE\n")
    for r in abertas[:n]:
        print(f"[{r['Nota']}] {r['Empresa']} | {r['Vaga']}\n     {r['Cidade']} · {r['Modalidade']} · "
              f"{r['Carga horária']} · publ. {r['Publicação']} · prazo {r['Prazo']}\n     {r['Link']}")
        if r.get("Alertas"):
            print(f"     ALERTA: {r['Alertas']}")
        print(f"     {r['Detalhe da nota']}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sem-alerta", action="store_true")
    ap.add_argument("--relatorio", action="store_true")
    ap.add_argument("--config")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = carregar_config(a.config)
    agora = datetime.now(TZ)
    hoje = agora.date()

    brutas, erros, fontes_ok = coletar_tudo(cfg)
    vagas, ids_abertos = processar(brutas, cfg, hoje)
    log.info("coletadas=%d filtradas=%d erros=%d", len(brutas), len(vagas), len(erros))

    if not brutas and erros:
        log.error("Nenhuma fonte respondeu; registro NÃO foi alterado.")
        if not a.sem_alerta:
            alertas.enviar("Bot de vagas: nenhuma fonte respondeu hoje.\n" + "\n".join(erros[:5]),
                           "Bot de vagas: falha na coleta")
        return 1

    reg = registro.abrir_registro()
    linhas, novas, mudancas = registro.mesclar(reg.ler(), vagas, fontes_ok, hoje.isoformat(), ids_abertos)
    reg.gravar(linhas)

    resumo_vigia = []
    try:
        from . import vigia
        plan = getattr(reg, "planilha", None)
        estado, avisos_vigia, resumo_vigia = vigia.verificar(cfg.get("vigia") or [], vigia.ler_estado(plan),
                                                             hoje.strftime("%d/%m/%Y"))
        vigia.gravar_estado(estado, plan)
        mudancas += avisos_vigia
    except Exception as e:  # noqa: BLE001
        log.warning("vigia de páginas falhou: %s", e)
    try:
        from .painel import atualizar_painel
        if hasattr(reg, "planilha"):
            atualizar_painel(reg.planilha, linhas, novas, agora)
    except Exception as e:  # noqa: BLE001
        log.warning("painel não atualizado: %s", e)
    try:
        from .site import gerar_site
        caminho = gerar_site(linhas, novas, cfg.get("empresas_alvo") or [], agora,
                             os.getenv("SITE_PATH", "_site/index.html"), resumo_vigia)
        log.info("site gerado em %s", caminho)
    except Exception as e:  # noqa: BLE001
        log.warning("site não gerado: %s", e)
    try:
        from .painel import atualizar_empresas
        if hasattr(reg, "planilha"):
            atualizar_empresas(reg.planilha, linhas, cfg.get("empresas_alvo") or [])
    except Exception as e:  # noqa: BLE001
        log.warning("aba Empresas não atualizada: %s", e)
    log.info("registro: total=%d novas=%d mudancas=%d (%s)", len(linhas), len(novas), len(mudancas),
             type(reg).__name__)

    if a.relatorio:
        imprimir_relatorio(linhas)

    if not a.sem_alerta:
        texto = alertas.montar_texto(novas, mudancas, erros, cfg["perfil"]["limiar_alerta"], hoje.strftime("%d/%m/%Y"))
        if texto:
            canais = alertas.enviar(texto, f"Vagas de estágio: {len(novas)} nova(s) · {hoje.strftime('%d/%m')}")
            log.info("alerta enviado por: %s", ", ".join(canais) or "nenhum canal configurado")
        else:
            log.info("nada novo acima do limiar; sem alerta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
