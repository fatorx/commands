// scanner_test.js — testes da varredura (client/scanner.js), sem navegador.
// Rodar: node --test tests/client/scanner_test.js   (o pytest chama isto em tests/test_client_scanner.py)
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const FONTE = fs.readFileSync(path.join(__dirname, '../../client/scanner.js'), 'utf8');

// ---- DOM mínimo: só o que o scanner usa ----

class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.parent = null;
    this.dataset = {};
    this.attrs = {};
    this.listeners = {};
    this.id = '';
    this._texto = '';
    this._classes = new Set();
    this.classList = {
      add: (...c) => c.forEach((x) => this._classes.add(x)),
      remove: (...c) => c.forEach((x) => this._classes.delete(x)),
      contains: (c) => this._classes.has(c),
    };
  }
  set className(v) {
    this._classes.clear();
    v.split(/\s+/).filter(Boolean).forEach((c) => this._classes.add(c));
  }
  set textContent(v) { this._texto = v; this.children = []; }
  get textContent() { return this._texto; }
  get firstChild() { return this.children[0] || null; }
  appendChild(filho) { filho.parent = this; this.children.push(filho); return filho; }
  insertBefore(filho, ref) {
    filho.parent = this;
    const i = this.children.indexOf(ref);
    this.children.splice(i < 0 ? this.children.length : i, 0, filho);
    return filho;
  }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this);
    this.parent = null;
  }
  setAttribute(nome, valor) { this.attrs[nome] = valor; }
  removeAttribute(nome) { delete this.attrs[nome]; }
  addEventListener(tipo, fn) { (this.listeners[tipo] ||= []).push(fn); }
  click() { (this.listeners.click || []).forEach((fn) => fn()); }
  scrollIntoView() {}
  focus() {}
  descendentes() { return this.children.flatMap((c) => [c, ...c.descendentes()]); }
}

// ---- relógio falso: Date.now e timers avançam só quando o teste manda ----

function criarRelogio() {
  let agora = 10_000;
  let proximoId = 1;
  const timers = new Map();
  const agendar = (fn, ms, intervalo) => {
    const id = proximoId++;
    timers.set(id, { fn, quando: agora + ms, intervalo });
    return id;
  };
  return {
    Date: { now: () => agora },
    setTimeout: (fn, ms) => agendar(fn, ms, null),
    setInterval: (fn, ms) => agendar(fn, ms, ms),
    clearTimeout: (id) => timers.delete(id),
    clearInterval: (id) => timers.delete(id),
    avancar(ms) {
      const fim = agora + ms;
      for (;;) {
        let proximo = null;
        for (const [id, t] of timers) {
          if (t.quando <= fim && (!proximo || t.quando < proximo[1].quando)) proximo = [id, t];
        }
        if (!proximo) break;
        const [id, t] = proximo;
        agora = t.quando;
        if (t.intervalo) t.quando += t.intervalo;
        else timers.delete(id);
        t.fn();
      }
      agora = fim;
    },
  };
}

// ---- montagem ----

const ACEITE = 700;
const DWELL = 900;
const FOLGA = 300; // maior que o debounce de 250 ms
const ESPACO = { key: ' ', preventDefault() {} };
const SETA_BAIXO = { key: 'ArrowDown', preventDefault() {} };

const MENU = [
  { cmd_id: 'testes', titulo: 'Executar testes', group: 'Ações' },
  { cmd_id: 'derrubar_containers', titulo: 'Derrubar containers', group: 'Infra', destructive: true },
  { cmd_id: 'voltar', titulo: 'Voltar' },
];

function montar(modo = 'passo', itens = MENU) {
  const relogio = criarRelogio();
  const sandbox = {
    window: {},
    Element,
    document: { createElement: (tag) => new Element(tag) },
    Date: relogio.Date,
    setTimeout: relogio.setTimeout,
    setInterval: relogio.setInterval,
    clearTimeout: relogio.clearTimeout,
    clearInterval: relogio.clearInterval,
  };
  vm.createContext(sandbox);
  vm.runInContext(FONTE, sandbox);

  const zona = new Element('div');
  zona.dataset.scan = 'true';
  const enviados = [];
  const scanner = new sandbox.window.Cockpit.Scanner({
    zona,
    cues: new Proxy({}, { get: () => () => {} }),
    config: { modo, dwell: DWELL, janelaAceite: ACEITE },
    onSelect: (intent) => enviados.push(intent.intent),
  });
  scanner.render(itens);

  const botoes = () => zona.descendentes().filter((e) => e.tag === 'button');
  return {
    relogio,
    scanner,
    zona,
    enviados,
    Scanner: sandbox.window.Cockpit.Scanner,
    atual: () => scanner.alvos[scanner.indice].textContent,
    titulos: () => botoes().map((b) => b.textContent),
    destacados: () => zona.descendentes().filter((e) => e.classList.contains('scanned')),
    marcados: () => zona.descendentes().filter((e) => e.attrs['aria-selected'] === 'true'),
    rotulo: (nome) => zona.descendentes().find((e) => e.classList.contains('grupo-rotulo') && e.textContent === nome),
    clicar(titulo) {
      const botao = botoes().find((b) => b.textContent === titulo);
      assert.ok(botao, `botão "${titulo}" não está na tela`);
      botao.click();
      relogio.avancar(FOLGA);
    },
    // switch: toque rápido (avança no passo; seleciona no autoscan)
    tocar() {
      scanner.pressionarInicio();
      relogio.avancar(50);
      scanner.pressionarFim();
      relogio.avancar(FOLGA);
    },
    // switch: segurar além da janela de aceite (seleciona no passo)
    segurar() {
      scanner.pressionarInicio();
      relogio.avancar(ACEITE + 10);
      scanner.pressionarFim();
      relogio.avancar(FOLGA);
    },
  };
}

// ---- invariante de zona ----

test('recusa container que não seja varrível (data-scan="true")', () => {
  const { Scanner } = montar();
  assert.throws(() => new Scanner({ zona: new Element('aside'), config: {} }), /data-scan/);
});

// ---- seleção por switch e teclado ----

test('passo: toque rápido avança sem selecionar', () => {
  const t = montar();
  assert.equal(t.atual(), 'Ações');
  t.tocar();
  assert.equal(t.atual(), 'Infra');
  assert.deepEqual(t.enviados, []);
});

test('passo: segurar o switch entra no grupo e seleciona o item', () => {
  const t = montar();
  t.segurar(); // entra em "Ações"
  t.tocar();   // "↑ Grupos" -> item
  assert.equal(t.atual(), 'Executar testes');
  t.segurar();
  assert.deepEqual(t.enviados, ['testes']);
});

test('passo: segurar espaço seleciona o item (com repetição de tecla)', () => {
  const t = montar();
  t.scanner.tecla(SETA_BAIXO); // Infra
  t.scanner.tecla(SETA_BAIXO); // Voltar (avulso)
  t.scanner.tecla(ESPACO);
  t.relogio.avancar(ACEITE / 2);
  t.scanner.tecla(ESPACO); // auto-repeat do teclado não reinicia a janela
  t.relogio.avancar(ACEITE);
  t.scanner.teclaUp(ESPACO);
  assert.deepEqual(t.enviados, ['voltar']);
});

test('autoscan: o cursor avança sozinho a cada dwell', () => {
  const t = montar('autoscan');
  assert.equal(t.atual(), 'Ações');
  t.relogio.avancar(DWELL);
  assert.equal(t.atual(), 'Infra');
});

test('autoscan: um toque entra no grupo e outro seleciona o item', () => {
  const t = montar('autoscan');
  t.tocar();               // entra em "Ações"
  t.relogio.avancar(DWELL); // "↑ Grupos" -> item
  assert.equal(t.atual(), 'Executar testes');
  t.tocar();
  assert.deepEqual(t.enviados, ['testes']);
});

// ---- debounce ----

test('autoscan: ricochete do switch não seleciona duas vezes', () => {
  const t = montar('autoscan', [{ cmd_id: 'voltar', titulo: 'Voltar' }]);
  t.scanner.pressionarInicio();
  t.relogio.avancar(100);
  t.scanner.pressionarInicio();
  assert.deepEqual(t.enviados, ['voltar']);
});

test('autoscan: ricochete após entrar no grupo não aciona o que está sob o cursor', () => {
  const t = montar('autoscan');
  t.scanner.pressionarInicio(); // entra em "Ações"
  t.relogio.avancar(100);
  t.scanner.pressionarInicio(); // ignorado: não volta aos grupos
  assert.equal(t.scanner.fase, 'coluna');
});

test('ponteiro: clique seleciona e clique duplo envia uma vez só', () => {
  const t = montar();
  t.clicar('Voltar');
  assert.deepEqual(t.enviados, ['voltar']);
  const botao = t.zona.descendentes().find((b) => b.textContent === 'Voltar');
  botao.click();
  t.relogio.avancar(100);
  botao.click();
  assert.deepEqual(t.enviados, ['voltar', 'voltar']);
});

// ---- confirmação destrutiva ----

test('destrutivo: primeira seleção só pede confirmação', () => {
  const t = montar();
  t.clicar('Derrubar containers');
  assert.deepEqual(t.enviados, []);
  assert.deepEqual(t.titulos(), ['Cancelar', 'Confirmar Derrubar containers?']);
  assert.equal(t.atual(), 'Cancelar'); // o cursor começa na opção segura
});

test('destrutivo: no autoscan, um segundo toque acidental cancela', () => {
  const t = montar('autoscan', [{ cmd_id: 'derrubar_containers', titulo: 'Derrubar containers', destructive: true }]);
  t.tocar(); // pede confirmação
  t.tocar(); // tremor: toque repetido antes de o cursor avançar
  assert.deepEqual(t.enviados, []);
  assert.deepEqual(t.titulos(), ['Derrubar containers']);
});

test('destrutivo: no passo, segurar de novo sem mover cancela', () => {
  const t = montar('passo', [{ cmd_id: 'derrubar_containers', titulo: 'Derrubar containers', destructive: true }]);
  t.segurar();
  t.segurar();
  assert.deepEqual(t.enviados, []);
  assert.deepEqual(t.titulos(), ['Derrubar containers']);
});

test('destrutivo: confirmar envia uma vez e restaura o menu', () => {
  const t = montar();
  t.clicar('Derrubar containers');
  t.clicar('Confirmar Derrubar containers?');
  assert.deepEqual(t.enviados, ['derrubar_containers']);
  assert.deepEqual(t.titulos(), ['Executar testes', 'Derrubar containers', 'Voltar']);
});

test('destrutivo: depois de confirmar, repetir pede nova confirmação (sem aninhar)', () => {
  const t = montar();
  t.clicar('Derrubar containers');
  t.clicar('Confirmar Derrubar containers?');
  t.clicar('Derrubar containers');
  assert.deepEqual(t.titulos(), ['Cancelar', 'Confirmar Derrubar containers?']);
  t.clicar('Cancelar');
  assert.deepEqual(t.enviados, ['derrubar_containers']);
});

test('destrutivo: cancelar não envia nada e restaura o menu', () => {
  const t = montar();
  t.clicar('Derrubar containers');
  t.clicar('Cancelar');
  assert.deepEqual(t.enviados, []);
  assert.deepEqual(t.titulos(), ['Executar testes', 'Derrubar containers', 'Voltar']);
});

test('destrutivo: fluxo completo só com o switch', () => {
  const t = montar();
  t.tocar();   // Infra
  t.segurar(); // entra em "Infra"
  t.tocar();   // Derrubar containers
  t.segurar(); // pede confirmação
  assert.equal(t.atual(), 'Cancelar');
  assert.deepEqual(t.enviados, []);
  t.tocar();   // move até "Confirmar"
  assert.equal(t.atual(), 'Confirmar Derrubar containers?');
  t.segurar(); // confirma
  assert.deepEqual(t.enviados, ['derrubar_containers']);
  assert.equal(t.atual(), 'Ações'); // de volta ao menu, pronto para varrer
});

// ---- cursor único ----

function assertCursorUnico(t) {
  const alvo = t.scanner.alvos[t.scanner.indice];
  assert.deepEqual(t.destacados().map((e) => e.textContent), [alvo.textContent]);
  assert.deepEqual(t.marcados().map((e) => e.textContent), [alvo.textContent]);
  assert.equal(t.zona.attrs['aria-activedescendant'], alvo.id);
}

test('cursor único ao entrar no grupo', () => {
  const t = montar();
  t.segurar();
  assertCursorUnico(t);
});

test('cursor único ao voltar para os grupos', () => {
  const t = montar();
  t.tocar();   // Infra
  t.segurar(); // entra em "Infra", cursor em "↑ Grupos"
  t.tocar();   // cursor sai do primeiro alvo
  t.clicar('↑ Grupos');
  assert.equal(t.scanner.fase, 'linha');
  assertCursorUnico(t);
});

test('cursor único ao entrar no grupo por clique no rótulo', () => {
  const t = montar();
  t.rotulo('Infra').click(); // cursor estava em "Ações"
  assertCursorUnico(t);
});

// ---- troca de grupo pelo ponteiro ----

function estadoDoGrupo(t, nome) {
  const { classList } = t.rotulo(nome).parent;
  return { ativo: classList.contains('ativo'), inativo: classList.contains('inativo') };
}

test('clicar em outro rótulo troca de grupo sem acumular estado', () => {
  const t = montar();
  t.rotulo('Ações').click();
  t.rotulo('Infra').click();
  assert.equal(t.titulos().filter((titulo) => titulo === '↑ Grupos').length, 1);
  assert.deepEqual(estadoDoGrupo(t, 'Infra'), { ativo: true, inativo: false });
  assert.deepEqual(estadoDoGrupo(t, 'Ações'), { ativo: false, inativo: true });
  assertCursorUnico(t);

  t.clicar('↑ Grupos');
  assert.ok(!t.titulos().includes('↑ Grupos'));
  for (const nome of ['Ações', 'Infra']) {
    assert.deepEqual(estadoDoGrupo(t, nome), { ativo: false, inativo: false });
  }
});
