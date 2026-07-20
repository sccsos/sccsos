<template>
  <div>
    <!-- Stat Cards -->
    <div class="grid">
      <div class="card">
        <div class="card-title">系统版本</div>
        <div class="stat-value blue">{{ health.version || '—' }}</div>
        <div class="stat-label">{{ health.initialized ? '已初始化' : '未初始化' }}</div>
      </div>
      <div class="card">
        <div class="card-title">Agent</div>
        <div class="stat-value green">{{ runningCount }}</div>
        <div class="stat-label">{{ agentCount }} 注册 / {{ failedCount }} 失败</div>
      </div>
      <div class="card">
        <div class="card-title">数据库</div>
        <div :class="['stat-value', dbOk ? 'green' : 'red']">{{ dbOk ? '✅' : '❌' }}</div>
        <div class="stat-label">{{ dbPath }}</div>
      </div>
      <div class="card">
        <div class="card-title">WebSocket</div>
        <div :class="['stat-value', wsConnected ? 'green' : 'red']">{{ wsConnected ? '🟢 在线' : '🔴 离线' }}</div>
        <div class="stat-label">实时事件流</div>
      </div>
    </div>

    <!-- Agent Status Distribution -->
    <h3 class="section-title">🤖 Agent 状态分布</h3>
    <div class="card" v-if="agents.length">
      <div class="status-bar">
        <div v-for="s in statusDist" :key="s.label"
             :style="{ width: s.pct + '%', background: s.color }"
             class="status-segment"
             :title="`${s.label}: ${s.count}`">
        </div>
      </div>
      <div class="status-legend">
        <span v-for="s in statusDist" :key="s.label" class="legend-item">
          <span class="dot" :style="{ background: s.color }"></span>
          {{ s.label }} ({{ s.count }})
        </span>
      </div>
    </div>
    <div v-else class="card"><p style="color:var(--text2)">暂无 Agent 数据</p></div>

    <!-- Quota + Billing -->
    <div class="grid-2" v-if="quota">
      <div class="card">
        <div class="card-title">📋 资源配额</div>
        <div style="margin-top:12px">
          <div class="row"><span>活跃 Agents</span><span>{{ quota.current_agents }} / {{ quota.max_agents }}</span></div>
          <div class="progress-bar"><div :class="['progress-fill', agentPct > 80 ? 'red' : agentPct > 50 ? 'amber' : 'green']" :style="{ width: agentPct + '%' }"></div></div>
          <div class="row" style="margin-top:12px"><span>今日 Tokens</span><span>{{ (quota.tokens_today / 1000).toFixed(1) }}K / {{ (quota.max_tokens_per_day / 1000).toFixed(0) }}K</span></div>
          <div class="progress-bar"><div :class="['progress-fill', tokenPct > 80 ? 'red' : tokenPct > 50 ? 'amber' : 'green']" :style="{ width: Math.min(tokenPct, 100) + '%' }"></div></div>
          <div class="row" style="margin-top:12px"><span>今日费用</span><span>${{ quota.cost_today.toFixed(4) }} / ${{ quota.max_cost_per_day.toFixed(2) }}</span></div>
          <div class="progress-bar"><div :class="['progress-fill', costPct > 80 ? 'red' : costPct > 50 ? 'amber' : 'green']" :style="{ width: Math.min(costPct, 100) + '%' }"></div></div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">💰 今日计费</div>
        <div style="margin-top:12px">
          <div class="stat-value blue" v-if="billing">${{ billing.total_cost?.toFixed(4) }}</div>
          <div v-if="billing">
            <div class="row"><span>调用次数</span><span>{{ billing.total_calls }}</span></div>
            <div class="row"><span>Token 总量</span><span>{{ billing.total_tokens?.toLocaleString() }}</span></div>
            <hr>
            <div v-for="(cost, model) in billing.by_model || {}" :key="model" class="row">
              <span>{{ model }}</span><span>${{ cost.toFixed(4) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Real-time Event Log -->
    <h3 class="section-title">⚡ 实时事件</h3>
    <div class="card event-log">
      <div v-if="eventLog.length === 0" style="color:var(--text2);padding:8px">等待事件...</div>
      <div v-for="(evt, i) in eventLog.slice(0, 20)" :key="i" class="event-row">
        <span class="event-time">{{ evt.time }}</span>
        <span :class="['event-tag', evtClass(evt.event)]">{{ evt.event }}</span>
        <span class="event-data">{{ evt.data }}</span>
      </div>
    </div>

    <!-- Agent List -->
    <h3 class="section-title">🤖 最近 Agents</h3>
    <div class="card" v-if="agents.length">
      <table>
        <thead><tr><th>名称</th><th>状态</th><th>版本</th><th>Token</th><th>错误</th></tr></thead>
        <tbody>
          <tr v-for="a in agents.slice(0, 10)" :key="a.id">
            <td><strong>{{ a.name || a.id }}</strong></td>
            <td><span :class="['tag', statusClass(a.status)]">{{ a.status }}</span></td>
            <td>{{ a.spec_version || '-' }}</td>
            <td>{{ (a.total_tokens || 0).toLocaleString() }}</td>
            <td>{{ a.error_count || 0 }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="card"><p style="color:var(--text2)">暂无 Agent 数据</p></div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { api } from '../api.js';
import { useWS } from '../ws.js';
import { useAgentsStore } from '../stores/agents.js';

const health = ref({});
const quota = ref(null);
const billing = ref(null);
const eventLog = ref([]);
const agentsStore = useAgentsStore();
const agents = computed(() => agentsStore.items);

const { connected: wsConnected, on, off } = useWS();
const wsEvents = [];
function onWS(event, fn) {
  wsEvents.push([event, fn]);
  on(event, fn);
}

const runningCount = computed(() => agents.value.filter(a => a.status === 'running').length);
const failedCount = computed(() => agents.value.filter(a => a.status === 'failed').length);
const agentCount = computed(() => agents.value.length);

// Status distribution for bar chart
const statusColors = { running: '#4ade80', paused: '#fbbf24', failed: '#f87171', created: '#38bdf8', terminated: '#94a3b8' };
const statusDist = computed(() => {
  const counts = {};
  agents.value.forEach(a => { counts[a.status] = (counts[a.status] || 0) + 1; });
  const total = agents.value.length || 1;
  return Object.entries(counts).map(([label, count]) => ({
    label, count, color: statusColors[label] || '#94a3b8',
    pct: Math.round(count / total * 100),
  }));
});

const dbOk = computed(() => health.value.database?.status === 'ok');
const dbPath = computed(() => health.value.database?.path || '');

const agentPct = computed(() => {
  if (!quota.value || !quota.value.max_agents) return 0;
  return Math.round(quota.value.current_agents / quota.value.max_agents * 100);
});
const tokenPct = computed(() => {
  if (!quota.value || !quota.value.max_tokens_per_day) return 0;
  return Math.round(quota.value.tokens_today / quota.value.max_tokens_per_day * 100);
});
const costPct = computed(() => {
  if (!quota.value || !quota.value.max_cost_per_day) return 0;
  return Math.round(quota.value.cost_today / quota.value.max_cost_per_day * 100);
});

function statusClass(s) {
  if (s === 'running') return 'ok';
  if (s === 'failed') return 'err';
  return 'warn';
}

function evtClass(e) {
  if (e?.includes('completed')) return 'ok';
  if (e?.includes('failed')) return 'err';
  return 'warn';
}

function addEvent(event, data) {
  const now = new Date();
  const time = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const dataStr = typeof data === 'string' ? data : JSON.stringify(data).slice(0, 80);
  eventLog.value.unshift({ time, event, data: dataStr });
  if (eventLog.value.length > 100) eventLog.value.length = 100;
}

async function load() {
  try {
    health.value = await api.health();
    await agentsStore.fetch();
    quota.value = await api.quota();
    const today = new Date().toISOString().slice(0, 10);
    billing.value = await api.billingSummary(today, today);
  } catch (e) {
    console.error('Dashboard load error:', e);
  }
}

// Auto-refresh on workflow events via WebSocket
onWS('workflow.started', (data) => { addEvent('workflow.started', data); setTimeout(load, 500); });
onWS('workflow.completed', (data) => { addEvent('workflow.completed', data); setTimeout(load, 500); });
onWS('workflow.failed', (data) => { addEvent('workflow.failed', data); setTimeout(load, 500); });

onMounted(load);

onUnmounted(() => {
  wsEvents.forEach(([event, fn]) => off(event, fn));
  wsEvents.length = 0;
});
</script>

<style scoped>
.status-bar {
  display: flex; height: 24px; border-radius: 6px; overflow: hidden; margin: 12px 0;
}
.status-segment { transition: width 0.3s ease; }
.status-legend { display: flex; gap: 16px; flex-wrap: wrap; }
.legend-item { font-size: 0.85rem; color: var(--text2); display: flex; align-items: center; gap: 4px; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.event-log { max-height: 300px; overflow-y: auto; }
.event-row { display: flex; gap: 12px; padding: 6px 0; border-bottom: 1px solid var(--bg3); font-size: 0.85rem; align-items: center; }
.event-row:last-child { border-bottom: none; }
.event-time { color: var(--text2); font-family: monospace; min-width: 70px; flex-shrink: 0; }
.event-tag { padding: 1px 6px; border-radius: 3px; font-size: 0.75rem; font-weight: 600; min-width: 100px; text-align: center; }
.event-tag.ok { background: rgba(74,222,128,0.15); color: var(--green); }
.event-tag.err { background: rgba(248,113,113,0.15); color: var(--red); }
.event-tag.warn { background: rgba(251,191,36,0.15); color: var(--amber); }
.event-data { color: var(--text2); font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
