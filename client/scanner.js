/* scanner.js — varredura sobre a Zona B (data-scan="true").

Dois modos (configuráveis por query string em app.js):
  - 'passo' (PADRÃO): step scanning — um toque rápido avança um item; SEGURAR o
    switch pela janela de aceite seleciona (hold-to-select).
  - 'autoscan': varre automaticamente com dwell ajustável; tocar seleciona.

Varredura linha-coluna: na fase LINHA, o cursor percorre os grupos (rótulos) e os
itens avulsos; selecionar um grupo entra na fase COLUNA (itens do grupo, com um
pseudo-item "↑ Grupos" para voltar). A Zona C (telemetria) nunca é varrida.

Earcons sintetizados via WebAudio com política de interrupção: um novo som
silencia o anterior (as dicas não colidem).
*/
(function () {
  'use strict';
  const Cockpit = (window.Cockpit = window.Cockpit || {});

  class AudioCues {
    constructor() {
      this.ctx = null;
      this._ativos = new Set();
    }
    _ctx() {
      if (!this.ctx) {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return null;
        this.ctx = new Ctx();
      }
      if (this.ctx.state === 'suspended') this.ctx.resume();
      return this.ctx;
    }
    _parar() {
      for (const osc of this._ativos) {
        try { osc.stop(); } catch (_) { /* já parado */ }
      }
      this._ativos.clear();
    }
    tom(freq, dur, tipo, ganho, atraso) {
      const ctx = this._ctx();
      if (!ctx) return;
      try {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = tipo || 'sine';
        osc.frequency.value = freq;
        const t = ctx.currentTime + (atraso || 0);
        g.gain.setValueAtTime(0.0001, t);
        g.gain.exponentialRampToValueAtTime(ganho || 0.12, t + 0.01);
        g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
        osc.connect(g);
        g.connect(ctx.destination);
        osc.start(t);
        osc.stop(t + dur + 0.02);
        this._ativos.add(osc);
        osc.onended = () => this._ativos.delete(osc);
      } catch (_) { /* áudio indisponível: segue em silêncio */ }
    }
    mover() { this._parar(); this.tom(440, 0.05, 'square', 0.05); }
    selecionar() { this._parar(); this.tom(880, 0.08, 'sine', 0.1); }
    sucesso() {
      this._parar();
      this.tom(660, 0.12, 'sine', 0.12);
      this.tom(990, 0.16, 'sine', 0.12, 0.1);
    }
    falha() { this._parar(); this.tom(200, 0.3, 'sawtooth', 0.1); }
    perigo() {
      this._parar();
      this.tom(1200, 0.1, 'square', 0.08);
      this.tom(1200, 0.1, 'square', 0.08, 0.14);
    }
    transicao(antes, depois) {
      const grave = ['unhealthy', 'down'];
      if (grave.includes(depois)) {
        this.perigo(); // ficou vermelho — chama atenção mesmo sem olhar
        return;
      }
      if (depois === 'healthy') {
        // chime suave ao ficar verde (amarelo->verde ou vermelho->verde)
        this._parar();
        this.tom(523, 0.12, 'sine', 0.08);
        this.tom(784, 0.16, 'sine', 0.08, 0.09);
        return;
      }
      // starting: neutro, sem ruído
    }
  }

  class Scanner {
    constructor({ zona, onSelect, cues, config }) {
      if (!(zona instanceof Element) || zona.dataset.scan !== 'true') {
        throw new Error('Scanner só aceita um container com data-scan="true" (Zona B)');
      }
      this.zona = zona;
      this.onSelect = onSelect;
      this.cues = cues;
      this.modo = (config && config.modo) || 'passo';          // 'passo' | 'autoscan'
      this.dwell = (config && config.dwell) || 900;            // ms por passo (autoscan)
      this.janelaAceite = (config && config.janelaAceite) || 700; // hold p/ aceitar (passo)

      this.timer = null;
      this.holdTimer = null;
      this._segurando = false;
      this.indice = -1;
      this.alvos = [];
      this.itensAlvo = [];
      this.ultimaAcao = 0;
      this._seq = 0;

      this.modoConfirmacao = false;
      this.ultimosDoServidor = [];
      this.baseConfirmacao = null;

      this.fase = 'linha'; // 'linha' | 'coluna'
      this.grupoAtivo = null;
      this.grupos = [];   // [{ nome, container, rotulo, itens, botoes }]
      this.avulsos = [];  // [{ item, botao }]
      this._pseudo = null;
    }

    // ---- render / modelo ----

    render(itens) {
      this.modoConfirmacao = false;
      this.ultimosDoServidor = itens;
      this._modelo(itens);
      this.fase = 'linha';
      this.grupoAtivo = null;
      this._refrescarAlvos();
      this._iniciar();
      this._focar();
    }

    _modelo(itens) {
      this.zona.textContent = '';
      this.grupos = [];
      this.avulsos = [];
      const porGrupo = new Map();
      const ordem = [];
      for (const item of itens) {
        if (item.group) {
          if (!porGrupo.has(item.group)) {
            porGrupo.set(item.group, []);
            ordem.push(item.group);
          }
          porGrupo.get(item.group).push(item);
        } else {
          this.avulsos.push({ item, botao: this._botao(item) });
        }
      }
      for (const nome of ordem) {
        const container = document.createElement('div');
        container.className = 'grupo';
        container.dataset.grupo = nome;
        container.setAttribute('role', 'group');
        const rotulo = document.createElement('div');
        rotulo.className = 'grupo-rotulo';
        rotulo.textContent = nome;
        rotulo.id = `opt-${this._seq++}`;
        rotulo.setAttribute('role', 'option');
        rotulo.tabIndex = -1; // foco fica na listbox; cursor segue aria-activedescendant
        container.appendChild(rotulo);
        const itens = porGrupo.get(nome);
        const botoes = itens.map((item) => this._botao(item, container));
        this.zona.appendChild(container);
        const grupo = { nome, container, rotulo, itens, botoes };
        rotulo.addEventListener('click', () => {
          this.cues.selecionar();
          this._entrarColuna(this.grupos.indexOf(grupo));
        });
        this.grupos.push(grupo);
      }
      for (const av of this.avulsos) this.zona.appendChild(av.botao);
    }

    _botao(item, pai) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'acao';
      b.dataset.cmdId = item.cmd_id;
      if (item.destructive) b.dataset.destrutivo = 'true';
      b.textContent = item.titulo;
      b.id = `opt-${this._seq++}`;
      b.setAttribute('role', 'option');
      b.tabIndex = -1; // foco fica na listbox; cursor segue aria-activedescendant
      b.addEventListener('click', () => this._aceitar(item));
      if (pai) pai.appendChild(b);
      return b;
    }

    mostrarConfirmacao(item) {
      this.baseConfirmacao = { intent: item.cmd_id, titulo: item.titulo };
      const anteriores = this.ultimosDoServidor; // preserva o menu real p/ cancelarConfirmacao
      this.render([
        { cmd_id: 'confirmar', titulo: `Confirmar ${item.titulo}?`, destructive: true },
        { cmd_id: 'cancelar', titulo: 'Cancelar' },
      ]);
      this.ultimosDoServidor = anteriores;
      this.modoConfirmacao = true;
      this.cues.perigo();
    }

    cancelarConfirmacao() {
      this.render(this.ultimosDoServidor);
    }

    // ---- alvos por fase ----

    _refrescarAlvos() {
      this.alvos = [];
      this.itensAlvo = [];
      this.indice = -1;
      if (this.fase === 'linha') {
        for (const g of this.grupos) {
          this.alvos.push(g.rotulo);
          this.itensAlvo.push({ tipo: 'grupo', grupo: g });
        }
        for (const av of this.avulsos) {
          this.alvos.push(av.botao);
          this.itensAlvo.push({ tipo: 'item', item: av.item });
        }
      } else {
        const g = this.grupos[this.grupoAtivo];
        if (this._pseudo) {
          this.alvos.push(this._pseudo);
          this.itensAlvo.push({ tipo: 'voltar_grupos' });
        }
        g.botoes.forEach((b, i) => {
          this.alvos.push(b);
          this.itensAlvo.push({ tipo: 'item', item: g.itens[i] });
        });
      }
    }

    _entrarColuna(idx) {
      this.fase = 'coluna';
      this.grupoAtivo = idx;
      const g = this.grupos[idx];
      g.container.classList.add('ativo');
      for (const outro of this.grupos) {
        if (outro !== g) outro.container.classList.add('inativo');
      }
      this._pseudo = document.createElement('button');
      this._pseudo.type = 'button';
      this._pseudo.className = 'acao pseudo-voltar';
      this._pseudo.textContent = '↑ Grupos';
      this._pseudo.id = `opt-${this._seq++}`;
      this._pseudo.setAttribute('role', 'option');
      this._pseudo.tabIndex = -1;
      this._pseudo.addEventListener('click', () => this._voltarGrupos());
      g.container.insertBefore(this._pseudo, g.container.firstChild);
      this._refrescarAlvos();
      this._iniciar();
      this._focar();
    }

    _voltarGrupos() {
      this.fase = 'linha';
      this.grupoAtivo = null;
      for (const g of this.grupos) g.container.classList.remove('ativo', 'inativo');
      if (this._pseudo) {
        this._pseudo.remove();
        this._pseudo = null;
      }
      this._refrescarAlvos();
      this._iniciar();
      this._focar();
    }

    // ---- cursor ----

    _iniciar() {
      if (this.timer) clearInterval(this.timer);
      this.timer = null;
      if (this.modo === 'autoscan' && this.alvos.length) {
        this.timer = setInterval(() => this._mover(1), this.dwell);
      }
      if (this.indice === -1 && this.alvos.length) this._mover(1, true);
    }

    _mover(passo, silencioso) {
      if (!this.alvos.length) return;
      if (this.alvos[this.indice]) this._desmarcar(this.alvos[this.indice]);
      this.indice = (this.indice + passo + this.alvos.length) % this.alvos.length;
      this._marcar(this.alvos[this.indice]);
      if (!silencioso) this.cues.mover();
    }

    _marcar(el) {
      el.classList.add('scanned');
      el.setAttribute('aria-selected', 'true');
      el.scrollIntoView({ block: 'nearest' });
      if (el.id) this.zona.setAttribute('aria-activedescendant', el.id);
    }

    _desmarcar(el) {
      el.classList.remove('scanned');
      el.removeAttribute('aria-selected');
    }

    _focar() {
      this.zona.setAttribute('tabindex', '-1');
      this.zona.focus({ preventScroll: true });
    }

    // ---- input (switch / teclado / ponteiro) ----

    pressionarInicio() {
      const agora = Date.now();
      if (agora - this.ultimaAcao < 250) return; // janela de aceite (debounce)
      if (this.modo === 'autoscan') {
        this.ultimaAcao = agora;
        this.aceitarAtual();
        return;
      }
      // passo: segurar seleciona; soltar rápido avança
      this._holdInicio = agora;
      this._holdTimer = setTimeout(() => {
        this._holdTimer = null;
        this.ultimaAcao = Date.now();
        this.aceitarAtual();
      }, this.janelaAceite);
    }

    pressionarFim() {
      if (this.modo !== 'passo') return;
      if (this._holdTimer) {
        clearTimeout(this._holdTimer);
        this._holdTimer = null;
        if (Date.now() - this.ultimaAcao >= 250) {
          this.ultimaAcao = Date.now();
          this._mover(1);
        }
      }
    }

    aceitarAtual() {
      const alvo = this.itensAlvo[this.indice];
      if (!alvo) return;
      if (alvo.tipo === 'grupo') {
        this.cues.selecionar();
        this._entrarColuna(this.grupos.indexOf(alvo.grupo));
        return;
      }
      if (alvo.tipo === 'voltar_grupos') {
        this.cues.selecionar();
        this._voltarGrupos();
        return;
      }
      this._aceitar(alvo.item);
    }

    _aceitar(item) {
      const agora = Date.now();
      if (agora - this.ultimaAcao < 250) return;
      this.ultimaAcao = agora;

      if (this.modoConfirmacao) {
        this.cues.selecionar();
        if (item.cmd_id === 'confirmar') {
          this.modoConfirmacao = false;
          this.onSelect(this.baseConfirmacao);
        } else {
          this.cancelarConfirmacao();
        }
        return;
      }

      if (item.destructive) {
        this.mostrarConfirmacao(item);
        return;
      }
      this.cues.selecionar();
      this.onSelect({ intent: item.cmd_id });
    }

    tecla(e) {
      if (e.key === ' ' || e.key === 'Enter') {
        e.preventDefault();
        if (!this._segurando) {
          this._segurando = true;
          this.pressionarInicio();
        }
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
        e.preventDefault();
        if (this.modo === 'autoscan') this._iniciar();
        this._mover(1);
      } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
        e.preventDefault();
        if (this.modo === 'autoscan') this._iniciar();
        this._mover(-1);
      }
    }

    teclaUp(e) {
      if (e.key === ' ' || e.key === 'Enter') {
        e.preventDefault();
        this._segurando = false;
        this.pressionarFim();
      }
    }
  }

  Cockpit.AudioCues = AudioCues;
  Cockpit.Scanner = Scanner;
})();