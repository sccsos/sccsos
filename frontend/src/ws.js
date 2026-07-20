/**
 * SCCS OS WebSocket Client — reactive real-time event stream.
 *
 * Connects to /api/v1/ws, auto-reconnects on disconnect,
 * and provides reactive event handlers for views.
 *
 * Usage:
 *   import { useWS } from '../ws.js';
 *   const { connected, on, off } = useWS();
 *   on('workflow.completed', (data) => { ... });
 *
 * Connection status is synced to the global app store automatically.
 */
import { ref, onMounted, onUnmounted } from 'vue';

// ── Singleton state ────────────────────────────────────────────────

let ws = null;
let reconnectTimer = null;
let handlers = {};
const WS_URL = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/v1/ws`;

export const connected = ref(false);

// ── Connection lifecycle ───────────────────────────────────────────

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  try {
    ws = new WebSocket(WS_URL);
  } catch (e) {
    console.warn('[WS] Connection failed:', e);
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    console.log('[WS] Connected');
    connected.value = true;
    clearTimeout(reconnectTimer);
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      const eventType = msg.event;
      if (eventType && handlers[eventType]) {
        handlers[eventType].forEach(fn => fn(msg));
      }
      // Also dispatch to wildcard '*'
      if (handlers['*']) {
        handlers['*'].forEach(fn => fn(msg));
      }
    } catch (e) {
      console.warn('[WS] Parse error:', e);
    }
  };

  ws.onclose = () => {
    console.log('[WS] Disconnected');
    connected.value = false;
    ws = null;
    scheduleReconnect();
  };

  ws.onerror = () => {
    // onerror triggers onclose, so reconnection is handled there
  };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, 3000);
}

function disconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = null;
  if (ws) {
    ws.onclose = null;  // prevent reconnect
    ws.close();
    ws = null;
  }
  connected.value = false;
}

// ── Public API ─────────────────────────────────────────────────────

export function useWS() {
  return {
    connected,

    /**
     * Register a handler for an event type.
     * @param {string} event - Event name, or '*' for all events
     * @param {Function} fn - Handler receiving parsed message object
     */
    on(event, fn) {
      if (!handlers[event]) handlers[event] = [];
      handlers[event].push(fn);
    },

    /**
     * Remove a specific event handler.
     */
    off(event, fn) {
      if (!handlers[event]) return;
      handlers[event] = handlers[event].filter(h => h !== fn);
    },

    /**
     * Manually connect (called automatically if autoConnect is used).
     */
    connect,

    /**
     * Manually disconnect.
     */
    disconnect,
  };
}

/**
 * Auto-connect on component mount, disconnect on unmount.
 * Use this in App.vue for session-level WS lifecycle.
 */
export function useAutoWS() {
  const wsAPI = useWS();

  onMounted(() => {
    // Small delay to let the app settle before WS connect
    setTimeout(connect, 500);
  });

  onUnmounted(() => {
    disconnect();
    handlers = {};
  });

  return wsAPI;
}
