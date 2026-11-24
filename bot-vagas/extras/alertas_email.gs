/**
 * Radar de vagas: alertas de vaga do Gmail -> planilha do robô.
 *
 * Lê os e-mails de alerta do Glassdoor e do Indeed e escreve uma linha por vaga na aba
 * "Alertas e-mail" desta planilha. O robô lê essa aba todo dia às 08:17 e passa as vagas
 * pelos mesmos filtros (região, área, nota).
 *
 * Também limpa a caixa de entrada: se NENHUMA vaga de um alerta serve para o perfil
 * (cidade fora da região, cargo sênior, operador, vendas...), o e-mail sai da caixa de entrada
 * e ganha a etiqueta "Vagas fora do perfil". Nada é apagado (veja ACAO_FORA_DO_PERFIL).
 * Só mexe em alertas do Glassdoor e do Indeed; nunca em Carreiras Unicamp, Gupy ou empresas.
 *
 * Instalação (uma vez): na planilha do robô, aberta com o e-mail que RECEBE os alertas,
 * vá em Extensões > Apps Script, cole este arquivo, salve, escolha a função "instalar"
 * e clique em Executar. Autorize. Pronto: roda sozinho a cada 2 horas.
 */

const ABA = 'Alertas e-mail';
const CABECALHO = ['ID', 'Fonte', 'Vaga', 'Empresa', 'Cidade', 'Link', 'Recebido em'];
const BUSCA = 'from:(noreply@glassdoor.com OR jobalert.indeed.com OR match.indeed.com) newer_than:4d';
const CIDADES = ['Campinas', 'Paulínia', 'Sumaré', 'Hortolândia', 'Jaguariúna', 'Valinhos', 'Vinhedo', 'Barão Geraldo'];
const GUARDAR_DIAS = 45;

// O que fazer com um alerta em que nenhuma vaga serve:
//   'arquivar' = tira da caixa de entrada e põe a etiqueta (dá para achar depois)
//   'lixeira'  = manda para a lixeira (o Gmail apaga de vez depois de 30 dias)
//   'nada'     = não mexe nos e-mails
const ACAO_FORA_DO_PERFIL = 'arquivar';
const ETIQUETA = 'Vagas fora do perfil';

// Regras simples, as mesmas ideias do robô: região, cargo de entrada, área.
const NAO_SERVE = ['senior', 'sr.', 'pleno', 'coordenador', 'coordenadora', 'gerente', 'supervisor', 'supervisora',
  'lider', 'especialista', 'diretor', 'diretora', 'head', 'operador', 'operadora', 'motorista', 'vendedor', 'vendedora',
  'vendas', 'comercial', 'consultor', 'consultora', 'representante', 'atendente', 'empilhadeira', 'ajudante',
  'auxiliar de producao', 'auxiliar de movimentacao', 'auxiliar de limpeza', 'aprendiz', 'tecnico', 'tecnica',
  'vigia', 'porteiro', 'recepcionista', 'telemarketing', 'sdr', 'cozinha', 'cozinheiro', 'churrasqueiro', 'garcom',
  'caixa de loja', 'repositor', 'estoquista', 'entregador', 'mecanico', 'eletricista', 'soldador', 'pedreiro'];
const AREA = ['estagio', 'estagiario', 'estagiaria', 'trainee', 'engenharia', 'engenheiro', 'engenheira', 'dados',
  'bi', 'planejamento', 'pcp', 'qualidade', 'processos', 'projetos', 'ambiental', 'meio ambiente', 'sustentabilidade',
  'agricola', 'agro', 'agronomia', 'supply', 'logistica', 'suprimentos', 'compras', 'administrativo', 'administrativa',
  'financeiro', 'financeira', 'controladoria', 'laboratorio', 'pesquisa', 'operacoes', 'analista', 'assistente de engenharia'];

/** Roda uma vez: cria os horários automáticos e já puxa os alertas dos últimos dias. */
function instalar() {
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === 'puxarAlertas'; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('puxarAlertas').timeBased().everyHours(2).create();
  const n = puxarAlertas();
  Logger.log('Instalado. Vagas novas encontradas agora: ' + n);
}

/** Lê os alertas recentes e acrescenta na aba as vagas que ainda não estão lá. */
function puxarAlertas() {
  const aba = pegarAba_();
  const ultima = aba.getLastRow();
  const existentes = new Set(ultima > 1 ? aba.getRange(2, 1, ultima - 1, 1).getValues().map(function (r) { return String(r[0]); }) : []);
  const novas = [];
  const foraDoPerfil = [];
  GmailApp.search(BUSCA, 0, 60).forEach(function (thread) {
    let lidas = 0;
    let servem = 0;
    thread.getMessages().forEach(function (m) {
      const de = m.getFrom();
      const recebido = Utilities.formatDate(m.getDate(), 'America/Sao_Paulo', 'yyyy-MM-dd');
      let vagas = [];
      try {
        if (/glassdoor/i.test(de)) vagas = lerGlassdoor(m.getBody());
        else if (/jobalert\.indeed/i.test(de)) vagas = lerIndeedAlerta(m.getPlainBody());
        else if (/match\.indeed/i.test(de)) vagas = lerIndeedMatch(m.getSubject(), m.getPlainBody() + ' ' + m.getBody());
      } catch (e) {
        Logger.log('Não consegui ler "' + m.getSubject() + '": ' + e);
      }
      lidas += vagas.length;
      servem += vagas.filter(serveProPerfil).length;
      vagas.forEach(function (v) {
        if (existentes.has(v.id)) return;
        existentes.add(v.id);
        novas.push([v.id, v.fonte, v.vaga, v.empresa, v.cidade, v.link, recebido]);
      });
    });
    // only touch alerts we could read, and only when not a single job fits
    if (lidas > 0 && servem === 0 && thread.isInInbox()) foraDoPerfil.push(thread);
  });
  limparCaixa_(foraDoPerfil);
  if (novas.length) aba.getRange(aba.getLastRow() + 1, 1, novas.length, CABECALHO.length).setValues(novas);
  limparAntigas_(aba);
  return novas.length;
}

// ---------- leitores (funções puras: recebem texto, devolvem vagas) ----------

/** Glassdoor: cada vaga é um link com jobListingId=...; dentro dele, empresa, cargo e cidade. */
function lerGlassdoor(html) {
  const porId = {};
  const re = /<a\b[^>]*href="([^"]*jobListingId=(\d+)[^"]*)"[^>]*>([\s\S]*?)<\/a>/gi;
  let m;
  while ((m = re.exec(html))) {
    const id = m[2];
    if (porId[id]) continue;
    const partes = textos_(m[3])
      .map(function (p) { return p.replace(/\s*\d[.,]\d\s*★?\s*$/, '').replace(/★/g, '').trim(); })
      .filter(function (p) {
        return p && !/^R\$|estimativa|candidatura|dia\(s\)|^\d+\s*h$|rec[ée]m|^novo$|^\d+([.,]\d+)?$/i.test(p);
      });
    if (partes.length < 3) continue;
    porId[id] = {
      id: 'glassdoor:' + id,
      fonte: 'Glassdoor',
      empresa: partes[0],
      vaga: partes[1],
      cidade: cidade_(partes[2]),
      link: 'https://www.glassdoor.com.br/partner/jobListing.htm?jobListingId=' + id,
    };
  }
  return Object.keys(porId).map(function (k) { return porId[k]; });
}

/** Indeed (alerta de busca): blocos "Cargo / Empresa - Cidade / ... / link com jk=". */
function lerIndeedAlerta(texto) {
  const out = [];
  String(texto).split(/\n\s*\n/).forEach(function (bloco) {
    const jk = (bloco.match(/[?&]jk=([0-9a-f]{16})/) || [])[1];
    if (!jk) return;
    const linhas = bloco.split('\n').map(function (l) { return l.trim(); }).filter(Boolean);
    if (linhas.length < 2) return;
    const segunda = linhas[1];
    const corte = segunda.lastIndexOf(' - ');
    out.push({
      id: 'indeed:' + jk,
      fonte: 'Indeed',
      vaga: linhas[0],
      empresa: corte > 0 ? segunda.slice(0, corte).trim() : segunda,
      cidade: cidade_(corte > 0 ? segunda.slice(corte + 3) : ''),
      link: 'https://br.indeed.com/viewjob?jk=' + jk,
    });
  });
  return out;
}

/** Indeed (vaga recomendada): uma vaga por e-mail; "Cargo na empresa Empresa" no assunto. */
function lerIndeedMatch(assunto, corpo) {
  const jk = (String(corpo).match(/jk=([0-9a-f]{16})/) || [])[1];
  const m = String(assunto).match(/^(.*) na empresa (.*)$/);
  if (!jk || !m) return [];
  const achada = CIDADES.filter(function (c) { return new RegExp('(^|[^\\wÀ-ú])' + c + '([^\\wÀ-ú]|$)', 'i').test(corpo); })[0] || '';
  return [{ id: 'indeed:' + jk, fonte: 'Indeed', vaga: m[1].trim(), empresa: m[2].trim(), cidade: achada, link: 'https://br.indeed.com/viewjob?jk=' + jk }];
}

/** Does this job fit? In the region (or remote), entry level, and in one of the areas. */
function serveProPerfil(v) {
  const titulo = semAcento_(v.vaga);
  const cidade = semAcento_(v.cidade);
  const regiao = CIDADES.some(function (c) { return semAcento_(c) === cidade; }) || /remot|home ?office/.test(titulo);
  const proibida = NAO_SERVE.some(function (p) { return temPalavra_(titulo, p); });
  const daArea = AREA.some(function (p) { return temPalavra_(titulo, p); });
  return regiao && !proibida && daArea;
}

// ---------- ajudantes ----------

function semAcento_(s) {
  return String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

function temPalavra_(texto, palavra) {
  const p = palavra.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp('(^|[^a-z0-9])' + p + '([^a-z0-9]|$)').test(texto);
}

function limparCaixa_(threads) {
  if (!threads.length || ACAO_FORA_DO_PERFIL === 'nada') return;
  if (ACAO_FORA_DO_PERFIL === 'lixeira') {
    threads.forEach(function (t) { t.moveToTrash(); });
  } else {
    const etiqueta = GmailApp.getUserLabelByName(ETIQUETA) || GmailApp.createLabel(ETIQUETA);
    threads.forEach(function (t) { t.addLabel(etiqueta).moveToArchive(); });
  }
  Logger.log(threads.length + ' alerta(s) sem nenhuma vaga para o perfil: ' + ACAO_FORA_DO_PERFIL);
}

function textos_(html) {
  return String(html)
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, '\n')
    .replace(/&nbsp;|&#160;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#x([0-9a-f]+);/gi, function (_, h) { return String.fromCharCode(parseInt(h, 16)); })
    .replace(/&#(\d+);/g, function (_, n) { return String.fromCharCode(Number(n)); })
    .split('\n')
    .map(function (s) { return s.replace(/[\s‌﻿]+/g, ' ').trim(); })
    .filter(Boolean);
}

/** "Campinas, São Paulo" -> "Campinas". */
function cidade_(s) {
  return String(s || '').split(',')[0].split('/')[0].trim();
}

function pegarAba_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let aba = ss.getSheetByName(ABA);
  if (!aba) {
    aba = ss.insertSheet(ABA);
    aba.getRange(1, 1, 1, CABECALHO.length).setValues([CABECALHO]).setFontWeight('bold');
    aba.setFrozenRows(1);
    aba.getRange('G:G').setNumberFormat('@'); // data como texto AAAA-MM-DD
  }
  return aba;
}

function limparAntigas_(aba) {
  const ultima = aba.getLastRow();
  if (ultima < 2) return;
  const limite = Utilities.formatDate(new Date(Date.now() - GUARDAR_DIAS * 864e5), 'America/Sao_Paulo', 'yyyy-MM-dd');
  const datas = aba.getRange(2, 7, ultima - 1, 1).getValues();
  for (let i = datas.length - 1; i >= 0; i--) {
    if (String(datas[i][0]) && String(datas[i][0]) < limite) aba.deleteRow(i + 2);
  }
}

// para testes fora do Google
if (typeof module !== 'undefined') module.exports = { lerGlassdoor: lerGlassdoor, lerIndeedAlerta: lerIndeedAlerta, lerIndeedMatch: lerIndeedMatch, serveProPerfil: serveProPerfil };
