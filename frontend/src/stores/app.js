/**
 * SCCS OS App Store — global reactive state for the admin SPA.
 *
 * Provides shared state across all views:
 * - health: server health info
 * - wsConnected: WebSocket connection status
 * - lastEvent: last WS event (for toast/notification)
 */
import { defineStore } from 'pinia';

export const useAppStore = defineStore('app', {
  state: () => ({
    version: '',
    wsConnected: false,
    lastEvent: null,
  }),

  actions: {
    setVersion(v) { this.version = v; },
    setWSConnected(v) { this.wsConnected = v; },
    pushEvent(event) { this.lastEvent = event; },
  },
});
