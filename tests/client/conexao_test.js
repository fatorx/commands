// conexao_test.js — testes da reconexão do cliente (client/conexao.js), sem navegador.
// Rodar: node --test tests/client/conexao_test.js   (o pytest chama isto em tests/test_client_conexao.py)
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { Conexao } = require('../../client/conexao.js');

class FakeSocket {
  constructor(url) {
    this.url = url;
    this.readyState = 0; // CONNECTING
    this.enviados = [];
    this.fechou = false;
  }
  send(d) { this.enviados.push(d); }
  close() { this.fechou = true; this.readyState = 3; }
  // ---- helpers de teste ----
  abrir() { this.readyState = 1; this.onopen(); }
  cair() { this.readyState = 3; this.onclose(); }
  receber(d) { this.onmessage({ data: d }); }
}

function montar(extra = {}) {
  const sockets = [];
  const estados = [];
  const mensagens = [];
  const timers = [];
  let proximoId = 1;
  const conexao = new Conexao({
    url: 'ws://x/',
    onMensagem: (d) => mensagens.push(d),
    onEstado: (e) => estados.push(e),
    criarSocket: (u) => { const s = new FakeSocket(u); sockets.push(s); return s; },
    setTimer: (fn, ms) => { const t = { id: proximoId++, fn, ms }; timers.push(t); return t.id; },
    clearTimer: (id) => { const i = timers.findIndex((t) => t.id === id); if (i >= 0) timers.splice(i, 1); },
    aleatorio: () => 0.5, // jitter neutro (fator 1.0)
    ...extra,
  });
  const dispararTimer = () => timers.shift().fn();
  return { conexao, sockets, estados, mensagens, timers, dispararTimer };
}

test('conecta: conectando -> conectado (primeira vez, sem "reconexao")', () => {
  const { conexao, sockets, estados } = montar();
  conexao.iniciar();
  sockets[0].abrir();
  assert.deepEqual(estados.map((e) => e.estado), ['conectando', 'conectado']);
  assert.equal(estados[1].reconexao, false);
  assert.equal(conexao.aberta, true);
});

test('repassa mensagens do socket atual', () => {
  const { conexao, sockets, mensagens } = montar();
  conexao.iniciar();
  sockets[0].abrir();
  sockets[0].receber('{"type":"status"}');
  assert.deepEqual(mensagens, ['{"type":"status"}']);
});

test('enviar: serializa quando aberto; devolve false e não envia quando fora', () => {
  const { conexao, sockets } = montar();
  conexao.iniciar();
  assert.equal(conexao.enviar({ type: 'intent' }), false); // ainda conectando
  sockets[0].abrir();
  assert.equal(conexao.enviar({ type: 'intent', intent: 'testes' }), true);
  assert.deepEqual(sockets[0].enviados, ['{"type":"intent","intent":"testes"}']);
  sockets[0].cair();
  assert.equal(conexao.enviar({ type: 'intent', intent: 'derrubar_containers' }), false);
  assert.equal(sockets[0].enviados.length, 1);
});

test('queda: marca "caiu", agenda retry; ao reabrir sinaliza reconexao e zera tentativas', () => {
  const { conexao, sockets, estados, timers, dispararTimer } = montar();
  conexao.iniciar();
  sockets[0].abrir();
  sockets[0].cair();
  const desc = estados.at(-1);
  assert.equal(desc.estado, 'desconectado');
  assert.equal(desc.caiu, true);
  assert.equal(desc.atrasoMs, 1000);
  assert.equal(timers.length, 1);

  dispararTimer();
  assert.equal(sockets.length, 2);
  assert.equal(estados.at(-1).estado, 'reconectando');
  sockets[1].abrir();
  assert.equal(estados.at(-1).estado, 'conectado');
  assert.equal(estados.at(-1).reconexao, true);
  assert.equal(conexao.tentativa, 0);
});

test('backoff exponencial com teto; "caiu" só na primeira queda', () => {
  const { conexao, sockets, estados, dispararTimer } = montar();
  conexao.iniciar();
  sockets[0].abrir();
  sockets[0].cair();
  const atrasos = [estados.at(-1).atrasoMs];
  const caiu = [estados.at(-1).caiu];
  for (let i = 0; i < 6; i++) {
    dispararTimer();
    sockets.at(-1).cair(); // a nova tentativa também falha
    atrasos.push(estados.at(-1).atrasoMs);
    caiu.push(estados.at(-1).caiu);
  }
  assert.deepEqual(atrasos, [1000, 2000, 4000, 8000, 10000, 10000, 10000]);
  assert.deepEqual(caiu, [true, false, false, false, false, false, false]);
});

test('jitter fica dentro de ±15% do atraso base', () => {
  for (const r of [0, 1]) {
    const { conexao, sockets, estados } = montar({ aleatorio: () => r });
    conexao.iniciar();
    sockets[0].abrir();
    sockets[0].cair();
    const ms = estados.at(-1).atrasoMs;
    assert.ok(ms >= 850 && ms <= 1150, `atraso ${ms} fora da faixa`);
  }
});

test('falha na primeira conexão: tenta de novo, sem "caiu"', () => {
  const { conexao, sockets, estados, dispararTimer } = montar();
  conexao.iniciar();
  sockets[0].cair(); // servidor ainda não está de pé
  assert.equal(estados.at(-1).estado, 'desconectado');
  assert.equal(estados.at(-1).caiu, false);
  dispararTimer();
  assert.equal(estados.at(-1).estado, 'reconectando');
  sockets[1].abrir();
  assert.equal(estados.at(-1).estado, 'conectado');
});

test('eventos de socket antigo são ignorados (sem timers duplicados)', () => {
  const { conexao, sockets, timers, dispararTimer, mensagens } = montar();
  conexao.iniciar();
  sockets[0].abrir();
  sockets[0].cair();
  dispararTimer(); // sockets[1] criado
  sockets[0].onclose(); // onclose tardio do socket velho
  sockets[0].receber('velho');
  assert.equal(timers.length, 0);
  assert.deepEqual(mensagens, []);
});

test('tentarAgora pula a espera sem duplicar tentativas', () => {
  const { conexao, sockets, timers } = montar();
  conexao.iniciar();
  sockets[0].abrir();
  sockets[0].cair();
  assert.equal(timers.length, 1);
  conexao.tentarAgora();
  assert.equal(timers.length, 0);
  assert.equal(sockets.length, 2);
  conexao.tentarAgora(); // já está tentando: nada a fazer
  assert.equal(sockets.length, 2);
});

test('parar: não reconecta e fecha o socket', () => {
  const { conexao, sockets, timers } = montar();
  conexao.iniciar();
  sockets[0].abrir();
  conexao.parar();
  sockets[0].cair();
  assert.equal(sockets[0].fechou, true);
  assert.equal(timers.length, 0);
});

test('criarSocket que lança agenda nova tentativa em vez de quebrar', () => {
  let n = 0;
  const { conexao, estados, timers } = montar({
    criarSocket: (u) => {
      n++;
      if (n === 1) throw new Error('URL inválida');
      return new FakeSocket(u);
    },
  });
  conexao.iniciar();
  assert.equal(estados.at(-1).estado, 'desconectado');
  assert.equal(timers.length, 1);
});

test('nada é reenviado automaticamente após reconectar (sem fila)', () => {
  const { conexao, sockets, dispararTimer } = montar();
  conexao.iniciar();
  sockets[0].abrir();
  sockets[0].cair();
  conexao.enviar({ type: 'intent', intent: 'derrubar_containers' }); // recusado
  dispararTimer();
  sockets[1].abrir();
  assert.deepEqual(sockets[1].enviados, []);
});
