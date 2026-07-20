/**
 * Agents Store — reactive agent lifecycle state.
 *
 * Caches agent list and provides actions for CRUD operations.
 * Other views (Dashboard, Agents page) share this cache.
 */
import { defineStore } from 'pinia';
import { api } from '../api.js';

export const useAgentsStore = defineStore('agents', {
  state: () => ({
    items: [],
    loading: false,
    error: null,
  }),

  getters: {
    running: (state) => state.items.filter(a => a.status === 'running'),
    failed: (state) => state.items.filter(a => a.status === 'failed'),
    count: (state) => state.items.length,
  },

  actions: {
    async fetch() {
      this.loading = true;
      this.error = null;
      try {
        this.items = await api.agents();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },

    async action(name, action) {
      await api.agentAction(name, action);
      await this.fetch();  // refresh after action
    },

    /** Called when a WS event indicates agent state may have changed. */
    invalidate() {
      this.fetch();
    },
  },
});
