/* app.js — cola o client ao WebSocket e à varredura.

Roteia as mensagens do protocolo: status -> Zona A, options -> Zona B (via
Scanner), result -> resultado falado/exibido. Panel entra no Dia 5 (Zona C).
Vanilla JS, sem build.
*/
(function () {
  'use strict';
  const $ = (sel) => document.querySelector(sel);
  const Cockpit = window.Cockpit;

  const audio = new Cockpit.AudioCues();
  const ws = new WebSocket(`ws://${location.host}/`);
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
    ws.send(JSON.stringify({ type: 'intent', intent: intent.intent, params: intent.params || {} }));
  }

  function renderizarStatus(msg) {
    $('#contexto').textContent = `workspace: ${(msg.context && msg.context.workspace) || '—'}`;
    const el = $('#conexao');
    el.textContent = 'conectado';
    el.className = 'estado conectado';
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

  ws.onmessage = (e) => {
    let msg;
    try {
      msg = JSON.parse(e.data);
    } catch (_) {
      return;
    }
    if (msg.type === 'status') renderizarStatus(msg);
    else if (msg.type === 'options') renderizarOptions(msg);
    else if (msg.type === 'result') renderizarResultado(msg);
    else if (msg.type === 'panel') renderizarPanel(msg);
  };

  ws.onclose = () => {
    const el = $('#conexao');
    el.textContent = 'desconectado';
    el.className = 'estado desconectado';
  };

  document.addEventListener('keydown', (e) => scanner.tecla(e));
  document.addEventListener('keyup', (e) => scanner.teclaUp(e));
  const switchBtn = $('#botao-switch');
  switchBtn.addEventListener('mousedown', () => scanner.pressionarInicio());
  switchBtn.addEventListener('mouseup', () => scanner.pressionarFim());
})();