<template>
  <div>
    <!-- Global Toggle -->
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">⚙️ 全局 Webhook 状态</div>
      <div style="margin-top:12px;display:flex;align-items:center;gap:16px">
        <span :class="['tag', enabled ? 'ok' : 'warn']" style="font-size:1rem;padding:4px 12px">
          {{ enabled ? '🟢 已启用' : '🔴 已禁用' }}
        </span>
        <button :class="['btn', enabled ? 'btn-red' : 'btn-green']" @click="toggle">
          {{ enabled ? '禁用' : '启用' }}
        </button>
      </div>
    </div>

    <!-- Add Webhook -->
    <h3 class="section-title">➕ 添加 Webhook</h3>
    <div class="card" style="margin-bottom:16px">
      <div class="add-form">
        <input v-model="form.url" placeholder="https://hooks.example.com/event" class="form-input" style="flex:2" />
        <input v-model="form.events" placeholder="事件 (逗号分隔, * 表示全部)" class="form-input" style="flex:1" />
        <button class="btn btn-accent" @click="addWebhook" :disabled="!form.url.trim()">添加</button>
      </div>
      <p v-if="addMsg" :style="{ color: addOk ? 'var(--green)' : 'var(--red)', marginTop: '8px', fontSize: '0.85rem' }">{{ addMsg }}</p>
    </div>

    <!-- Webhook List -->
    <h3 class="section-title">📋 已配置端点</h3>
    <div class="card">
      <table v-if="endpoints.length">
        <thead><tr><th>URL</th><th>事件</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="(ep, i) in endpoints" :key="i">
            <td style="font-family:monospace;font-size:0.8rem">{{ ep.url }}</td>
            <td>
              <span v-for="e in (ep.events || ['*'])" :key="e" class="tag info" style="margin:2px">{{ e }}</span>
            </td>
            <td><span :class="['tag', ep.enabled !== false ? 'ok' : 'warn']">{{ ep.enabled !== false ? '启用' : '禁用' }}</span></td>
            <td><button class="btn btn-xs btn-red" @click="removeWebhook(ep.url)">删除</button></td>
          </tr>
        </tbody>
      </table>
      <p v-else style="color:var(--text2);padding:12px;text-align:center">暂无 Webhook 端点</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';

const enabled = ref(false);
const endpoints = ref([]);
const form = ref({ url: '', events: '*' });
const addMsg = ref('');
const addOk = ref(false);

async function load() {
  try {
    const resp = await fetch('/api/v1/webhooks');
    if (resp.ok) {
      const data = await resp.json();
      enabled.value = data.enabled;
      endpoints.value = data.endpoints;
    }
  } catch (e) {
    console.error('Webhook load error:', e);
  }
}

async function toggle() {
  try {
    const resp = await fetch('/api/v1/webhooks/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !enabled.value }),
    });
    if (resp.ok) {
      enabled.value = !enabled.value;
    }
  } catch (e) {
    console.error(e);
  }
}

async function addWebhook() {
  addMsg.value = '';
  try {
    const events = form.value.events.split(',').map(e => e.trim()).filter(Boolean);
    const resp = await fetch('/api/v1/webhooks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: form.value.url.trim(), events }),
    });
    if (resp.ok) {
      form.value = { url: '', events: '*' };
      addMsg.value = '✅ Webhook 已添加';
      addOk.value = true;
      await load();
    } else {
      const err = await resp.text();
      addMsg.value = `❌ 添加失败: ${err}`;
      addOk.value = false;
    }
  } catch (e) {
    addMsg.value = `❌ 添加失败: ${e.message}`;
    addOk.value = false;
  }
}

async function removeWebhook(url) {
  try {
    await fetch(`/api/v1/webhooks?url=${encodeURIComponent(url)}`, { method: 'DELETE' });
    await load();
  } catch (e) {
    console.error(e);
  }
}

onMounted(load);
</script>

<style scoped>
.add-form { display: flex; gap: 8px; align-items: center; }
.form-input { background: var(--bg3); color: var(--text); border: 1px solid var(--bg3); border-radius: 6px; padding: 8px 12px; font-size: 0.9rem; }
.form-input:focus { outline: none; border-color: var(--accent); }
.btn-accent { background: var(--accent); color: var(--bg); border: none; padding: 8px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; }
.btn-accent:hover { filter: brightness(1.2); }
.btn-accent:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-xs { padding: 2px 8px; font-size: 0.8rem; border: 1px solid var(--bg3); border-radius: 4px; cursor: pointer; background: var(--bg2); color: var(--text); }
.btn-green { border-color: var(--green); color: var(--green); background: transparent; border: 1px solid var(--green); padding: 6px 14px; border-radius: 6px; cursor: pointer; }
.btn-red { border-color: var(--red); color: var(--red); background: transparent; border: 1px solid var(--red); padding: 6px 14px; border-radius: 6px; cursor: pointer; }
.btn-xs.btn-red { padding: 2px 8px; }
</style>
