<template>
  <div class="app-layout">
    <div class="sidebar-overlay" :class="{ visible: sidebarOpen }" @click="sidebarOpen = false"></div>
    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <div class="sidebar-header">
        <div class="logo">SCCS OS</div>
        <div class="version">{{ store.version }}</div>
      </div>
      <nav class="nav">
        <router-link to="/" class="nav-item" :class="{ active: $route.path === '/' }" @click="sidebarOpen = false">
          <span class="nav-icon">📊</span> 概览
        </router-link>
        <router-link to="/agents" class="nav-item" :class="{ active: $route.path === '/agents' }" @click="sidebarOpen = false">
          <span class="nav-icon">🤖</span> Agents
        </router-link>
        <router-link to="/quota" class="nav-item" :class="{ active: $route.path === '/quota' }" @click="sidebarOpen = false">
          <span class="nav-icon">📋</span> 配额
        </router-link>
        <router-link to="/billing" class="nav-item" :class="{ active: $route.path === '/billing' }" @click="sidebarOpen = false">
          <span class="nav-icon">💰</span> 计费
        </router-link>
        <router-link to="/skills" class="nav-item" :class="{ active: $route.path === '/skills' }" @click="sidebarOpen = false">
          <span class="nav-icon">🧩</span> 技能市场
        </router-link>
        <router-link to="/traces" class="nav-item" :class="{ active: $route.path === '/traces' }" @click="sidebarOpen = false">
          <span class="nav-icon">🔄</span> 追踪
        </router-link>
        <router-link to="/webhooks" class="nav-item" :class="{ active: $route.path === '/webhooks' }" @click="sidebarOpen = false">
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
        <button class="hamburger" @click="sidebarOpen = !sidebarOpen" aria-label="Toggle menu">
          <span></span><span></span><span></span>
        </button>
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
const sidebarOpen = ref(false);

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

<style scoped>
.sidebar-overlay {
  display: none;
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.5);
  z-index: 99;
}
.sidebar-overlay.visible {
  display: none;
}
.hamburger {
  display: none;
  flex-direction: column;
  gap: 4px;
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px;
}
.hamburger span {
  display: block;
  width: 20px;
  height: 2px;
  background: var(--text);
  border-radius: 2px;
  transition: 0.2s;
}

@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    top: 0; left: 0;
    height: 100vh;
    z-index: 100;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
  }
  .sidebar.open {
    transform: translateX(0);
  }
  .sidebar-overlay.visible {
    display: block;
  }
  .hamburger {
    display: flex;
  }
  .main-content {
    padding-top: 0;
  }
  .top-bar h2 {
    font-size: 1rem;
  }
}
</style>
