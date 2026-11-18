"""Gera o site pessoal (GitHub Pages): uma página HTML com todas as vagas abertas.

O HTML é gerado a cada execução, com os dados embutidos (não precisa de servidor).
Não inclui a coluna "Minhas notas" (o site é acessível por link).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .text import contains_any, norm


def _dados(linhas: list[dict], novas_ids: set[str], empresas: list[dict], agora: datetime) -> dict:
    vagas = []
    for r in linhas:
        if str(r.get("Verificação", "")).startswith("não listada"):
            continue
        vagas.append({
            "id": r.get("ID", ""), "nota": int(r.get("Nota") or 0), "status": r.get("Status", ""),
            "tipo": r.get("Tipo", "Estágio"), "empresa": r.get("Empresa", ""), "vaga": r.get("Vaga", ""),
            "cidade": str(r.get("Cidade", "")).split(",")[0], "modalidade": r.get("Modalidade", ""),
            "carga": r.get("Carga horária", ""), "cursos": r.get("Cursos aceitos", ""),
            "bolsa": r.get("Bolsa e benefícios", ""), "prazo": str(r.get("Prazo", "")),
            "publicacao": str(r.get("Publicação", "")), "alertas": r.get("Alertas", ""),
            "link": r.get("URL") or r.get("Link") or "", "verificacao": r.get("Verificação", ""),
            "nova": r.get("ID") in novas_ids,
        })
    emp = []
    for e in empresas:
        apel = [a.strip() for a in e.get("apelidos", [e["nome"]])]
        n = sum(1 for v in vagas if v["status"] not in ("encerrada", "descartada")
                and contains_any(norm(v["empresa"] + " " + v["vaga"]), apel))
        emp.append({"polo": e["polo"], "nome": e["nome"], "cidade": e.get("cidade", ""), "setor": e.get("setor", ""),
                    "busca": e.get("busca", e["nome"]), "n": n})
    return {"atualizado": agora.strftime("%d/%m/%Y às %H:%M"), "hoje": agora.strftime("%Y-%m-%d"),
            "vagas": vagas, "empresas": emp}


def gerar_site(linhas: list[dict], novas: list[dict], empresas: list[dict], agora: datetime,
               destino: str = "_site/index.html") -> str:
    dados = _dados(linhas, {r.get("ID") for r in novas}, empresas, agora)
    js = json.dumps(dados, ensure_ascii=False).replace("</", "<\\/")
    html = MODELO.replace("__DADOS__", js)
    p = Path(destino)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")
    (p.parent / ".nojekyll").write_text("", encoding="utf-8")
    return str(p)


MODELO = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Radar de vagas</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Public+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --campo:#EEF2EA; --folha:#FFFFFF; --tinta:#1B2620; --terra:#5C6B63; --sulco:#D5DDD2;
  --lavoura:#2F6B3F; --broto:#7FA86A; --trigo:#C9951F; --palha:#9AA79F; --alerta:#9A3B22;
  --raio:14px;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--campo);color:var(--tinta);font:16px/1.5 "Public Sans",system-ui,sans-serif}
a{color:inherit}
.casca{max-width:760px;margin:0 auto;padding:28px 18px 80px}
header h1{font-family:"Bricolage Grotesque",system-ui,sans-serif;font-weight:800;font-size:clamp(2.1rem,7vw,3.1rem);
  line-height:1;letter-spacing:-.02em;margin:0}
.resumo{margin:12px 0 0;font-size:1.05rem;color:var(--terra);max-width:60ch}
.resumo b{color:var(--tinta);font-weight:600}
.atualizado{font-size:.85rem;color:var(--palha);margin-top:6px}
nav.abas{display:flex;gap:6px;margin:26px 0 14px;border-bottom:1px solid var(--sulco)}
nav.abas button{appearance:none;border:0;background:none;font:600 1rem "Public Sans",sans-serif;color:var(--terra);
  padding:10px 4px;margin-right:16px;border-bottom:3px solid transparent;cursor:pointer}
nav.abas button[aria-selected=true]{color:var(--tinta);border-color:var(--lavoura)}
.filtros{display:grid;gap:10px;margin-bottom:18px}
.linha{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.linha span.rot{font-size:.85rem;color:var(--terra);margin-right:4px;min-width:52px}
.chip{appearance:none;border:1px solid var(--sulco);background:var(--folha);color:var(--tinta);border-radius:999px;
  padding:6px 13px;font:500 .9rem "Public Sans",sans-serif;cursor:pointer}
.chip[aria-pressed=true]{background:var(--tinta);color:#fff;border-color:var(--tinta)}
input[type=search]{width:100%;border:1px solid var(--sulco);background:var(--folha);border-radius:10px;padding:11px 14px;
  font:1rem "Public Sans",sans-serif;color:var(--tinta)}
:focus-visible{outline:3px solid var(--broto);outline-offset:2px}
.contagem{font-size:.9rem;color:var(--terra);margin:4px 0 12px}
.cartao{position:relative;display:grid;grid-template-columns:56px 1fr;gap:0 16px;background:var(--folha);
  border-radius:var(--raio);padding:18px 18px 16px 0;margin-bottom:12px;border:1px solid var(--sulco);overflow:hidden}
.cartao.oculta{display:none}
.planta{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:6px;padding-left:14px}
.haste{width:10px;flex:1;min-height:70px;background:var(--campo);border-radius:6px;position:relative;overflow:hidden}
.haste i{position:absolute;left:0;right:0;bottom:0;border-radius:6px;transition:height .9s cubic-bezier(.2,.8,.2,1)}
.nota{font:800 1.35rem/1 "Bricolage Grotesque",sans-serif}
.alta i{background:var(--lavoura)} .alta .nota{color:var(--lavoura)}
.media i{background:var(--trigo)}  .media .nota{color:#8A6510}
.baixa i{background:var(--palha)}  .baixa .nota{color:var(--terra)}
.topo{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px}
.tag{font-size:.75rem;font-weight:600;padding:2px 9px;border-radius:999px;background:var(--campo);color:var(--terra)}
.tag.nova{background:var(--lavoura);color:#fff}
.tag.urgente{background:#F6E7BF;color:#7A5608}
.tag.status{background:#DCE8F7;color:#1F4E86}
.cartao h2{font:700 1.18rem/1.25 "Bricolage Grotesque",sans-serif;margin:0 0 2px;letter-spacing:-.01em}
.empresa{font-weight:600;color:var(--terra);margin-bottom:8px}
.meta{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:.92rem;color:var(--tinta);margin-bottom:10px}
.meta span{white-space:nowrap}
.alertas{font-size:.86rem;color:var(--alerta);margin:0 0 10px;max-width:62ch}
details{font-size:.88rem;color:var(--terra);margin-bottom:12px}
details summary{cursor:pointer;width:max-content}
details dl{display:grid;grid-template-columns:max-content 1fr;gap:3px 12px;margin:8px 0 0}
details dt{font-weight:600;color:var(--tinta)}
details dd{margin:0}
.acoes{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.ver{display:inline-block;background:var(--lavoura);color:#fff;text-decoration:none;font-weight:600;
  padding:10px 18px;border-radius:10px}
.ver:hover{background:#245632}
.secund{appearance:none;background:none;border:1px solid var(--sulco);border-radius:10px;padding:9px 13px;
  font:500 .9rem "Public Sans",sans-serif;color:var(--terra);cursor:pointer}
.secund[aria-pressed=true]{border-color:var(--trigo);color:#7A5608;background:#FBF3DC}
.vazio{background:var(--folha);border:1px dashed var(--sulco);border-radius:var(--raio);padding:28px;text-align:center;color:var(--terra)}
.polo{margin:26px 0 8px;font:700 1.15rem "Bricolage Grotesque",sans-serif}
.emp{display:grid;grid-template-columns:1fr auto;gap:4px 12px;align-items:center;background:var(--folha);
  border:1px solid var(--sulco);border-radius:12px;padding:12px 14px;margin-bottom:8px}
.emp strong{display:block}
.emp small{color:var(--terra)}
.emp .n{font:800 1.2rem "Bricolage Grotesque",sans-serif;text-align:right}
.emp .n.zero{color:var(--palha);font-weight:600;font-size:.9rem}
.emp .links{grid-column:1/-1;display:flex;gap:14px;font-size:.9rem}
.emp .links a{color:var(--lavoura);font-weight:600}
@media (prefers-reduced-motion:reduce){.haste i{transition:none}}
@media (max-width:420px){.cartao{grid-template-columns:46px 1fr;gap:0 12px}.planta{padding-left:10px}}
</style>
</head>
<body>
<div class="casca">
<header>
  <h1>Radar de vagas</h1>
  <p class="resumo" id="resumo"></p>
  <p class="atualizado" id="atualizado"></p>
</header>

<nav class="abas" role="tablist">
  <button role="tab" aria-selected="true" data-aba="vagas">Vagas</button>
  <button role="tab" aria-selected="false" data-aba="empresas">Empresas da região</button>
</nav>

<section id="aba-vagas">
  <div class="filtros">
    <input type="search" id="busca" placeholder="Buscar por empresa, cargo ou palavra (ex.: dados, Paulínia)" aria-label="Buscar vagas">
    <div class="linha" id="f-tipo"><span class="rot">Tipo</span></div>
    <div class="linha" id="f-cidade"><span class="rot">Cidade</span></div>
    <div class="linha" id="f-nota"><span class="rot">Nota</span></div>
    <div class="linha" id="f-extra"><span class="rot">Mostrar</span></div>
  </div>
  <p class="contagem" id="contagem" aria-live="polite"></p>
  <div id="lista"></div>
</section>

<section id="aba-empresas" hidden>
  <p class="resumo">O número mostra quantas vagas de cada empresa o radar encontrou hoje. Zero quer dizer só que ela não publicou nas fontes do radar: use os links para conferir.</p>
  <div id="empresas"></div>
</section>
</div>

<script>
const D = __DADOS__;
const guardar = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
const ler = (k, padrao) => { try { return JSON.parse(localStorage.getItem(k)) ?? padrao; } catch (e) { return padrao; } };
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const salvas = new Set(ler("salvas", []));
const escondidas = new Set(ler("escondidas", []));

function dataBR(s){ return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s.slice(8,10)+"/"+s.slice(5,7)+"/"+s.slice(0,4) : s; }
function isoDe(s){ const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(s); return m ? `${m[3]}-${m[2]}-${m[1]}` : (/^\d{4}-\d{2}-\d{2}$/.test(s) ? s : ""); }
function diasAte(s){ const iso = isoDe(s); if(!iso) return null; return Math.round((new Date(iso+"T12:00") - new Date(D.hoje+"T12:00"))/864e5); }
const faixa = n => n >= 75 ? "alta" : n >= 55 ? "media" : "baixa";

const abertas = D.vagas.filter(v => !["encerrada","descartada"].includes(v.status));
const urgentes = abertas.filter(v => { const d = diasAte(v.prazo); return d !== null && d >= 0 && d <= 7; });
const novas = abertas.filter(v => v.nova);
document.getElementById("resumo").innerHTML =
  `<b>${abertas.length}</b> oportunidades abertas em Campinas e região, <b>${novas.length}</b> novas hoje e <b>${urgentes.length}</b> com prazo terminando nesta semana.`;
document.getElementById("atualizado").textContent = "Atualizado em " + D.atualizado;

const estado = { tipo: "Todos", cidade: "Todas", nota: 0, salvas: false, escondidas: false, busca: "" };
function grupoChips(id, chave, opcoes){
  const el = document.getElementById(id);
  opcoes.forEach(([valor, rotulo]) => {
    const b = document.createElement("button");
    b.className = "chip"; b.type = "button"; b.textContent = rotulo;
    b.setAttribute("aria-pressed", estado[chave] === valor);
    b.onclick = () => { estado[chave] = valor; el.querySelectorAll(".chip").forEach(c => c.setAttribute("aria-pressed", c === b)); desenhar(); };
    el.appendChild(b);
  });
}
const tipos = [...new Set(D.vagas.map(v => v.tipo))].sort();
grupoChips("f-tipo", "tipo", [["Todos","Todos"], ...tipos.map(t => [t, t])]);
const cidades = [...new Set(abertas.map(v => v.cidade).filter(Boolean))].sort((a,b) => a.localeCompare(b, "pt"));
grupoChips("f-cidade", "cidade", [["Todas","Todas"], ...cidades.map(c => [c, c])]);
grupoChips("f-nota", "nota", [[0,"Qualquer"], [55,"55 ou mais"], [75,"75 ou mais"]]);
(function(){
  const el = document.getElementById("f-extra");
  [["salvas","Só as salvas"],["escondidas","As que escondi"]].forEach(([k, r]) => {
    const b = document.createElement("button"); b.className = "chip"; b.type = "button"; b.textContent = r;
    b.setAttribute("aria-pressed", false);
    b.onclick = () => { estado[k] = !estado[k]; b.setAttribute("aria-pressed", estado[k]); desenhar(); };
    el.appendChild(b);
  });
})();
document.getElementById("busca").addEventListener("input", e => { estado.busca = e.target.value.toLowerCase(); desenhar(); });

function cartao(v){
  const d = diasAte(v.prazo);
  const tags = [];
  if (v.nova) tags.push(`<span class="tag nova">Nova hoje</span>`);
  tags.push(`<span class="tag">${esc(v.tipo)}</span>`);
  if (d !== null && d >= 0 && d <= 7) tags.push(`<span class="tag urgente">${d === 0 ? "Prazo termina hoje" : d === 1 ? "Falta 1 dia" : `Faltam ${d} dias`}</span>`);
  if (v.status && v.status !== "nova") tags.push(`<span class="tag status">${esc(v.status)}</span>`);
  if (/^NÃO CONFIRMADA/i.test(v.verificacao)) tags.push(`<span class="tag">Abertura não confirmada</span>`);
  const meta = [v.cidade, v.modalidade && v.modalidade !== "não informada" ? v.modalidade : "",
                v.carga && v.carga !== "não informada" ? v.carga : "",
                v.prazo && isoDe(v.prazo) ? "prazo " + dataBR(isoDe(v.prazo)) : ""].filter(Boolean);
  const salva = salvas.has(v.id), oculta = escondidas.has(v.id);
  return `<article class="cartao ${faixa(v.nota)}" data-id="${esc(v.id)}">
    <div class="planta" aria-label="Nota ${v.nota} de 100"><div class="haste"><i style="height:0" data-h="${v.nota}"></i></div><div class="nota">${v.nota}</div></div>
    <div>
      <div class="topo">${tags.join("")}</div>
      <h2>${esc(v.vaga)}</h2>
      <div class="empresa">${esc(v.empresa)}</div>
      <div class="meta">${meta.map(m => `<span>${esc(m)}</span>`).join("")}</div>
      ${v.alertas ? `<p class="alertas">${esc(v.alertas)}</p>` : ""}
      <details><summary>Detalhes</summary><dl>
        <dt>Cursos</dt><dd>${esc(v.cursos || "não especificado")}</dd>
        <dt>Bolsa e benefícios</dt><dd>${esc(v.bolsa || "não publicado")}</dd>
        <dt>Publicada em</dt><dd>${esc(dataBR(isoDe(v.publicacao) || v.publicacao) || "não informado")}</dd>
      </dl></details>
      <div class="acoes">
        ${v.link ? `<a class="ver" href="${esc(v.link)}" target="_blank" rel="noopener noreferrer">Ver vaga e candidatar</a>` : ""}
        <button class="secund" type="button" data-acao="salvar" aria-pressed="${salva}">${salva ? "Salva" : "Salvar"}</button>
        <button class="secund" type="button" data-acao="esconder">${oculta ? "Mostrar de novo" : "Esconder"}</button>
      </div>
    </div></article>`;
}

function desenhar(){
  const q = estado.busca;
  const lista = D.vagas.filter(v => {
    if (["encerrada","descartada"].includes(v.status)) return false;
    if (estado.tipo !== "Todos" && v.tipo !== estado.tipo) return false;
    if (estado.cidade !== "Todas" && v.cidade !== estado.cidade) return false;
    if (v.nota < estado.nota) return false;
    if (estado.salvas && !salvas.has(v.id)) return false;
    if (estado.escondidas !== escondidas.has(v.id)) return false;
    if (q && !(v.vaga + " " + v.empresa + " " + v.cidade + " " + v.cursos).toLowerCase().includes(q)) return false;
    return true;
  }).sort((a, b) => b.nota - a.nota);
  const el = document.getElementById("lista");
  document.getElementById("contagem").textContent = lista.length === 1 ? "1 oportunidade" : `${lista.length} oportunidades`;
  el.innerHTML = lista.length ? lista.map(cartao).join("")
    : `<div class="vazio">Nenhuma oportunidade com esses filtros. Tente limpar a busca ou escolher "Qualquer" na nota.</div>`;
  requestAnimationFrame(() => el.querySelectorAll(".haste i").forEach(i => i.style.height = i.dataset.h + "%"));
}

document.getElementById("lista").addEventListener("click", e => {
  const b = e.target.closest("button[data-acao]"); if (!b) return;
  const id = b.closest(".cartao").dataset.id;
  if (b.dataset.acao === "salvar") { salvas.has(id) ? salvas.delete(id) : salvas.add(id); guardar("salvas", [...salvas]); }
  else { escondidas.has(id) ? escondidas.delete(id) : escondidas.add(id); guardar("escondidas", [...escondidas]); }
  desenhar();
});

(function(){
  const el = document.getElementById("empresas"); let polo = "";
  el.innerHTML = D.empresas.map(e => {
    const cab = e.polo !== polo ? `<h3 class="polo">${esc(e.polo)}</h3>` : ""; polo = e.polo;
    const gupy = "https://portal.gupy.io/job-search/term=" + encodeURIComponent(e.busca);
    const lkd = "https://www.linkedin.com/jobs/search/?keywords=" + encodeURIComponent(e.busca) +
                "&location=" + encodeURIComponent(e.cidade.split("/")[0].trim() + ", São Paulo, Brasil");
    return cab + `<div class="emp"><div><strong>${esc(e.nome)}</strong><small>${esc(e.cidade)}, ${esc(e.setor)}</small></div>
      <div class="n ${e.n ? "" : "zero"}">${e.n ? e.n + (e.n === 1 ? " vaga" : " vagas") : "nenhuma hoje"}</div>
      <div class="links"><a href="${gupy}" target="_blank" rel="noopener noreferrer">Procurar na Gupy</a>
      <a href="${lkd}" target="_blank" rel="noopener noreferrer">Procurar no LinkedIn</a></div></div>`;
  }).join("");
})();

document.querySelectorAll("nav.abas button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav.abas button").forEach(x => x.setAttribute("aria-selected", x === b));
  document.getElementById("aba-vagas").hidden = b.dataset.aba !== "vagas";
  document.getElementById("aba-empresas").hidden = b.dataset.aba !== "empresas";
});
desenhar();
</script>
</body>
</html>
"""
