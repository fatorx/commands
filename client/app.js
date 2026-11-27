/* app.js — cola o client ao WebSocket (com reconexão, ver conexao.js) e à varredura.

Roteia as mensagens do protocolo: status -> Zona A (contexto), options -> Zona B
(via Scanner), result -> resultado falado/exibido, panel -> Zona C (telemetria,
nunca varrida). A badge de conexão da Zona A segue o estado real do enlace.
Vanilla JS, sem build.
*/
(function () {
  'use strict';
  const $ = (sel) => document.querySelector(sel);
  const Cockpit = window.Cockpit;

  const audio = new Cockpit.AudioCues();
  const zonaB = $('#lista-zona-b');

  const params = new URLSearchParams(location.search);
  const config = {
    modo: params.get('modo') || 'passo',                      // 'passo' (padrão) | 'autoscan'
    dwell: parseInt(params.get('dwell'), 10) || 900,          // ms por passo no autoscan
    janelaAceite: parseInt(params.get('aceite'), 10) || 700,  // hold p/ aceitar no passo
  };

  const scanner = new Cockpit.Scanner({
    zona: zonaB,
    cues: audio,
    config,
    onSelect: (intent) => {
      const item = itensPorId.get(intent.intent);
      if (item && item.detalhe_fala) falar(item.detalhe_fala);
      enviarIntent(intent);
    },
  });

  let itensPorId = new Map();
  const estadosInfra = new Map(); // nome do serviço -> último estado (earcons)

  function enviarIntent(intent) {
    const enviado = conexao.enviar({
      type: 'intent', intent: intent.intent, params: intent.params || {},
    });
    if (!enviado) {
      // Nunca enfileira: reexecutar às cegas, depois, um comando destrutivo seria
      // perigoso. O usuário é avisado e repete a ação quando reconectar.
      const aviso = 'Sem conexão com o servidor. A ação não foi enviada.';
      $('#resultado').textContent = aviso;
      audio.falha();
      falar(aviso);
    }
  }

  // A badge de conexão (Zona A) segue o estado REAL do enlace, não uma mensagem
  // `status` do servidor. Zonas B/C ficam esmaecidas enquanto os dados podem estar velhos.
  function renderizarConexao(info) {
    const el = $('#conexao');
    if (info.estado === 'conectado') {
      el.textContent = 'conectado';
      el.className = 'estado conectado';
      if (info.reconexao) {
        audio.sucesso();
        falar('Conexão restabelecida.');
      }
    } else if (info.estado === 'desconectado') {
      const seg = Math.max(1, Math.round((info.atrasoMs || 0) / 1000));
      el.textContent = `desconectado — nova tentativa em ${seg}s (#${info.tentativa})`;
      el.className = 'estado desconectado';
      if (info.caiu) {
        audio.perigo();
        falar('Conexão perdida. Reconectando.');
      }
    } else {
      el.textContent = info.estado === 'reconectando' ? 'reconectando…' : 'conectando…';
      el.className = 'estado';
    }
    document.body.dataset.conexao = info.estado;
  }

  function renderizarStatus(msg) {
    $('#contexto').textContent = `workspace: ${(msg.context && msg.context.workspace) || '—'}`;
  }

  function renderizarOptions(msg) {
    $('#titulo-zona-b').textContent = msg.title || '';
    itensPorId = new Map(msg.items.map((i) => [i.cmd_id, i]));
    scanner.render(msg.items);
  }

  function renderizarResultado(msg) {
    const el = $('#resultado');
    el.textContent = `${msg.titulo}: ${msg.detalhe}`;
    if (msg.ok) audio.sucesso();
    else audio.falha();
    if (msg.detalhe_fala) falar(msg.detalhe_fala);
  }

  function renderizarPanel(msg) {
    const card = document.querySelector(`#zona-c [data-region="${msg.region}"]`);
    if (!card) return;
    const corpo = card.querySelector('.card-corpo');
    if (msg.region === 'infra') {
      const ul = document.createElement('ul');
      ul.className = 'semafaros';
      (msg.data.semafaros || []).forEach((s) => {
        const antes = estadosInfra.get(s.nome);
        if (antes && antes !== s.estado) audio.transicao(antes, s.estado);
        estadosInfra.set(s.nome, s.estado);
        const li = document.createElement('li');
        li.className = `semafaro ${s.estado || ''}`;
        li.textContent = s.nome;
        const st = document.createElement('span');
        st.className = 'semafaro-estado';
        st.textContent = s.estado;
        li.appendChild(st);
        ul.appendChild(li);
      });
      corpo.replaceChildren(ul);
    } else if (msg.region === 'git') {
      const d = msg.data || {};
      corpo.textContent = `${d.branch || '—'} · ${d.alteracoes ?? 0} alterações`;
    } else if (msg.region === 'health') {
      const d = msg.data || {};
      const cx = d.complexidade_max || {};
      const rotulo = document.createElement('div');
      rotulo.className = 'barra-rotulo';
      rotulo.textContent =
        `Complexidade máx: ${cx.modulo || '—'} ${cx.score ?? 0} (${cx.nivel || ''})`;
      const barra = document.createElement('div');
      barra.className = 'barra';
      const preenchimento = document.createElement('div');
      preenchimento.className = 'barra-preenchimento';
      preenchimento.style.width = `${Math.min(100, ((cx.score || 0) / 25) * 100)}%`;
      barra.appendChild(preenchimento);
      const resumo = document.createElement('div');
      resumo.className = 'barra-rotulo';
      resumo.textContent =
        `Duplicação ${d.duplicacao_pct ?? 0}% · Alertas de arquitetura ${d.alertas_arquitetura ?? 0}`;
      corpo.replaceChildren(rotulo, barra, resumo);
    }
  }

  function falar(texto) {
    if (!texto || !('speechSynthesis' in window)) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(texto);
    u.lang = 'pt-BR';
    speechSynthesis.speak(u);
  }

  function aoReceber(dados) {
    let msg;
    try {
      msg = JSON.parse(dados);
    } catch (_) {
      return;
    }
    if (msg.type === 'status') renderizarStatus(msg);
    else if (msg.type === 'options') renderizarOptions(msg);
    else if (msg.type === 'result') renderizarResultado(msg);
    else if (msg.type === 'panel') renderizarPanel(msg);
  }

  // Declarada por último: os callbacks acima já existem. Ao reconectar, o servidor
  // reenvia status/options/panels e o cliente se ressincroniza (a confirmação
  // destrutiva pendente também é descartada pelo novo `options`).
  const conexao = new Cockpit.Conexao({
    url: `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/`,
    onMensagem: aoReceber,
    onEstado: renderizarConexao,
  });
  window.addEventListener('online', () => conexao.tentarAgora());
  conexao.iniciar();

  document.addEventListener('keydown', (e) => scanner.tecla(e));
  document.addEventListener('keyup', (e) => scanner.teclaUp(e));
  const switchBtn = $('#botao-switch');
  switchBtn.addEventListener('mousedown', () => scanner.pressionarInicio());
  switchBtn.addEventListener('mouseup', () => scanner.pressionarFim());
})();