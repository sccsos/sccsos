<template>
  <div class="app-layout">
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="logo">SCCS OS</div>
        <div class="version">{{ store.version }}</div>
      </div>
      <nav class="nav">
        <router-link to="/" class="nav-item" :class="{ active: $route.path === '/' }">
          <span class="nav-icon">📊</span> 概览
        </router-link>
        <router-link to="/agents" class="nav-item" :class="{ active: $route.path === '/agents' }">
          <span class="nav-icon">🤖</span> Agents
        </router-link>
        <router-link to="/quota" class="nav-item" :class="{ active: $route.path === '/quota' }">
          <span class="nav-icon">📋</span> 配额
        </router-link>
        <router-link to="/billing" class="nav-item" :class="{ active: $route.path === '/billing' }">
          <span class="nav-icon">💰</span> 计费
        </router-link>
        <router-link to="/skills" class="nav-item" :class="{ active: $route.path === '/skills' }">
          <span class="nav-icon">🧩</span> 技能市场
        </router-link>
        <router-link to="/traces" class="nav-item" :class="{ active: $route.path === '/traces' }">
          <span class="nav-icon">🔄</span> 追踪
        </router-link>
        <router-link to="/webhooks" class="nav-item" :class="{ active: $route.path === '/webhooks' }">
          <span class="nav-icon">🔔</span> Webhooks
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <div class="status-dot" :class="connected ? 'online' : 'offline'"></div>
        {{ connected ? '已连接' : '离线' }}
      </div>
    </aside>
    <main class="main-content">
      <div class="top-bar">
        <h2>{{ $route.name }}</h2>
        <div class="top-bar-actions">
          <button class="btn btn-sm" @click="refresh">🔄 刷新</button>
        </div>
      </div>
      <div class="content-area">
        <router-view @refresh="refresh" />
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { api } from './api.js';
import { useWS, connected } from './ws.js';
import { useAppStore } from './stores/app.js';
import { onMounted } from 'vue';

const store = useAppStore();

const ws = useWS();

async function refresh() {
  try {
    const h = await api.health();
    store.setVersion(`v${h.version}`);
  } catch {
    // WS handles connection status
  }
}

// Sync WS status to store
import { watch } from 'vue';
watch(connected, (v) => store.setWSConnected(v));

onMounted(() => {
  refresh();
  setTimeout(() => ws.connect(), 500);
});
</script>
