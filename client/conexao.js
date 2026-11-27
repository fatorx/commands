/* conexao.js — enlace WebSocket com reconexão automática.

Backoff exponencial com jitter (atrasoMin -> atrasoMax). Após reconectar, o servidor
reenvia status/options/panels, então o estado do cliente se ressincroniza sozinho.

Decisão de segurança: intents enviados com o enlace fora NÃO são enfileirados nem
reenviados — `enviar` devolve false e quem chamou avisa o usuário. Reexecutar
depois, às cegas, um "derrubar containers" seria perigoso.

Dependências injetáveis (criarSocket, setTimer, clearTimer, aleatorio) para testar
em Node sem navegador. Vanilla JS, sem build.
*/
(function () {
  'use strict';
  const Cockpit = (typeof window !== 'undefined' ? (window.Cockpit = window.Cockpit || {}) : {});

  const ABERTO = 1; // WebSocket.OPEN

  class Conexao {
    constructor({
      url,
      onMensagem,
      onEstado,
      criarSocket = (u) => new WebSocket(u),
      setTimer = (fn, ms) => setTimeout(fn, ms),
      clearTimer = (id) => clearTimeout(id),
      aleatorio = Math.random,
      atrasoMin = 1000,
      atrasoMax = 10000,
    }) {
      this.url = url;
      this.onMensagem = onMensagem;
      this.onEstado = onEstado || (() => {});
      this._criarSocket = criarSocket;
      this._setTimer = setTimer;
      this._clearTimer = clearTimer;
      this._aleatorio = aleatorio;
      this.atrasoMin = atrasoMin;
      this.atrasoMax = atrasoMax;

      this.socket = null;
      this.tentativa = 0;      // falhas consecutivas desde a última conexão
      this._timer = null;
      this._jaConectou = false;
      this._parado = false;
    }

    get aberta() {
      return !!this.socket && this.socket.readyState === ABERTO;
    }

    iniciar() {
      this._parado = false;
      this._conectar();
    }

    parar() {
      this._parado = true;
      if (this._timer !== null) this._clearTimer(this._timer);
      this._timer = null;
      if (this.socket) this.socket.close();
    }

    /** true se enviou; false se o enlace está fora (nada é enfileirado). */
    enviar(objeto) {
      if (!this.aberta) return false;
      this.socket.send(JSON.stringify(objeto));
      return true;
    }

    /** Pula a espera do backoff (ex.: o navegador voltou a ficar online). */
    tentarAgora() {
      if (this._parado || this.aberta || this._timer === null) return;
      this._clearTimer(this._timer);
      this._timer = null;
      this._conectar();
    }

    _atraso() {
      const base = Math.min(this.atrasoMax, this.atrasoMin * 2 ** (this.tentativa - 1));
      return Math.round(base * (0.85 + 0.3 * this._aleatorio())); // jitter ±15%
    }

    _conectar() {
      this._timer = null;
      this.onEstado({
        estado: this._jaConectou || this.tentativa > 0 ? 'reconectando' : 'conectando',
        tentativa: this.tentativa,
      });
      let socket;
      try {
        socket = this._criarSocket(this.url);
      } catch (_) {
        this._agendar();
        return;
      }
      this.socket = socket;
      // Eventos de um socket antigo (já substituído) são ignorados.
      socket.onopen = () => {
        if (this.socket !== socket) return;
        const reconexao = this._jaConectou;
        this._jaConectou = true;
        this.tentativa = 0;
        this.onEstado({ estado: 'conectado', tentativa: 0, reconexao });
      };
      socket.onmessage = (e) => {
        if (this.socket !== socket) return;
        this.onMensagem(e.data);
      };
      socket.onclose = () => {
        if (this.socket !== socket || this._parado) return;
        const caiu = this._jaConectou && this.tentativa === 0;
        this._agendar(caiu);
      };
      // onerror é sempre seguido de onclose: a reconexão sai de lá.
      socket.onerror = () => {};
    }

    _agendar(caiu) {
      this.tentativa += 1;
      const atrasoMs = this._atraso();
      this.onEstado({ estado: 'desconectado', tentativa: this.tentativa, atrasoMs, caiu: !!caiu });
      this._timer = this._setTimer(() => this._conectar(), atrasoMs);
    }
  }

  Cockpit.Conexao = Conexao;
  if (typeof module !== 'undefined' && module.exports) module.exports = { Conexao };
})();
