<template>
  <div>
    <!-- Stat Cards Row 1 -->
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
        <div class="stat-label">{{ eventLog.length }} 事件 / 今日 {{ todayEvents }} 事件</div>
      </div>
    </div>

    <!-- Token Consumption Trend (SVG sparkline) -->
    <h3 class="section-title">📈 Token 消耗趋势 (最近 60 秒)</h3>
    <div class="card chart-card">
      <svg :viewBox="`0 0 ${CHART_W} ${CHART_H}`" class="sparkline" v-if="trendPoints.length > 1">
        <polyline :points="trendPath" fill="none" stroke="#4ade80" stroke-width="2" stroke-linecap="round"/>
        <circle v-for="(p, i) in trendPoints" :key="i"
                v-if="i === trendPoints.length - 1"
                :cx="p.x" :cy="p.y" r="3" fill="#4ade80"/>
      </svg>
      <div v-else style="color:var(--text2);padding:12px 0;text-align:center">等待 Token 数据...</div>
      <div class="trend-footer">
        <span>当前: <strong>{{ lastTokenValue }}</strong> tokens/分</span>
        <span>峰值: <strong>{{ peakTokenValue }}</strong> tokens/分</span>
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

    <!-- Skill Market Summary -->
    <h3 class="section-title">🏪 技能市场摘要</h3>
    <div class="card" v-if="skillSummary">
      <div class="grid-4">
        <div class="mini-stat"><span class="num">{{ skillSummary.total || 0 }}</span><span class="lbl">总计</span></div>
        <div class="mini-stat"><span class="num green">{{ skillSummary.approved || 0 }}</span><span class="lbl">已发布</span></div>
        <div class="mini-stat"><span class="num amber">{{ skillSummary.pending || 0 }}</span><span class="lbl">待审</span></div>
        <div class="mini-stat"><span class="num blue">{{ skillSummary.installed || 0 }}</span><span class="lbl">已安装</span></div>
      </div>
    </div>
    <div v-else class="card"><p style="color:var(--text2)">加载中...</p></div>

    <!-- Real-time Event Log -->
    <h3 class="section-title">⚡ 实时事件</h3>
    <div class="card event-log">
      <div class="event-log-actions">
        <span style="color:var(--text2);font-size:0.85rem">{{ eventLog.length }} 事件 / 最近 100 条</span>
        <button class="btn-small" @click="eventLog = []">清空</button>
      </div>
      <div v-if="eventLog.length === 0" style="color:var(--text2);padding:8px">等待事件...</div>
      <div v-for="(evt, i) in eventLog.slice(0, 30)" :key="i" class="event-row">
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

// ── Constants ─────────────────────────────────────────────────
const CHART_W = 400;
const CHART_H = 60;
const MAX_TREND = 60;  // keep last 60 data points

// ── State ──────────────────────────────────────────────────────
const health = ref({});
const quota = ref(null);
const billing = ref(null);
const skillSummary = ref(null);
const eventLog = ref([]);
const todayEvents = ref(0);
const agentsStore = useAgentsStore();
const agents = computed(() => agentsStore.items);

// Token trend tracking (tokens per minute, rolling window)
const trendPoints = ref([]);
const peakTokenValue = ref(0);

const { connected: wsConnected, on, off } = useWS();
const wsEvents = [];

const runningCount = computed(() => agents.value.filter(a => a.status === 'running').length);
const failedCount = computed(() => agents.value.filter(a => a.status === 'failed').length);
const agentCount = computed(() => agents.value.length);

// ── Status Distribution ───────────────────────────────────────
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

const lastTokenValue = computed(() => {
  if (!trendPoints.value.length) return 0;
  return trendPoints.value[trendPoints.value.length - 1].value;
});

// ── Trend Chart SVG Path ──────────────────────────────────────
const trendPath = computed(() => {
  if (trendPoints.value.length < 2) return '';
  return trendPoints.value.map(p => `${p.x},${p.y}`).join(' ');
});

// ── Helpers ────────────────────────────────────────────────────
function statusClass(s) {
  if (s === 'running') return 'ok';
  if (s === 'failed') return 'err';
  return 'warn';
}

function evtClass(e) {
  if (e?.includes('completed') || e?.includes('approved')) return 'ok';
  if (e?.includes('failed') || e?.includes('rejected') || e?.includes('error')) return 'err';
  return 'warn';
}

function addEvent(event, data) {
  const now = new Date();
  const time = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const dataStr = typeof data === 'string' ? data : JSON.stringify(data).slice(0, 80);
  eventLog.value.unshift({ time, event, data: dataStr });
  if (eventLog.value.length > 100) eventLog.value.length = 100;
  todayEvents.value++;
}

function recordTokenPoint(tokens) {
  const value = typeof tokens === 'number' ? tokens : parseInt(tokens) || 0;
  if (value > peakTokenValue.value) peakTokenValue.value = value;

  const points = [...trendPoints.value, { x: 0, y: 0, value }];
  // Keep window
  if (points.length > MAX_TREND) points.splice(0, points.length - MAX_TREND);

  // Compute x,y positions for SVG
  const w = CHART_W - 10;
  const h = CHART_H - 10;
  const maxVal = Math.max(...points.map(p => p.value), 1);
  points.forEach((p, i) => {
    p.x = 5 + (i / Math.max(points.length - 1, 1)) * w;
    p.y = 5 + h - (p.value / maxVal) * h;
  });
  trendPoints.value = points;
}

function onWS(event, fn) {
  wsEvents.push([event, fn]);
  on(event, fn);
}

async function load() {
  try {
    health.value = await api.health();
    await agentsStore.fetch();
    quota.value = await api.quota();
    const today = new Date().toISOString().slice(0, 10);
    billing.value = await api.billingSummary(today, today);

    // Skill market summary
    const skills = await api.get('/api/v1/skills/reviews?status=all');
    const installed = await api.get('/api/v1/skills/installed');
    skillSummary.value = {
      total: skills.length,
      approved: skills.filter(s => s.status === 'approved').length,
      pending: skills.filter(s => s.status === 'pending_review').length,
      installed: installed.length,
    };
  } catch (e) {
    console.error('Dashboard load error:', e);
  }
}

// ── WebSocket event wiring ────────────────────────────────────
// Workflow events — refresh data
onWS('workflow.started', (data) => { addEvent('workflow.started', data); setTimeout(load, 500); });
onWS('workflow.completed', (data) => { addEvent('workflow.completed', data); setTimeout(load, 500); });
onWS('workflow.failed', (data) => { addEvent('workflow.failed', data); setTimeout(load, 500); });

// Agent lifecycle events — live badge updates
onWS('agent.started', (data) => { addEvent('agent.started', data); setTimeout(load, 300); });
onWS('agent.stopped', (data) => { addEvent('agent.stopped', data); setTimeout(load, 300); });
onWS('agent.paused', (data) => { addEvent('agent.paused', data); setTimeout(load, 300); });
onWS('agent.resumed', (data) => { addEvent('agent.resumed', data); setTimeout(load, 300); });
onWS('agent.failed', (data) => { addEvent('agent.failed', data); setTimeout(load, 300); });
onWS('agent.created', (data) => { addEvent('agent.created', data); setTimeout(load, 300); });

// Skill market events
onWS('skill.submitted', (data) => { addEvent('skill.submitted', data); setTimeout(load, 500); });
onWS('skill.approved', (data) => { addEvent('skill.approved', data); setTimeout(load, 500); });
onWS('skill.rejected', (data) => { addEvent('skill.rejected', data); setTimeout(load, 500); });
onWS('skill.rated', (data) => { addEvent('skill.rated', data); });

// Simulate token trend from billing refresh
let trendInterval = null;

onMounted(() => {
  load();
  // Collect token data every 10s from billing refresh
  trendInterval = setInterval(async () => {
    try {
      const today = new Date().toISOString().slice(0, 10);
      const bill = await api.billingSummary(today, today);
      if (bill?.total_tokens != null) {
        // Track tokens per 10s slice as a trend data point
        recordTokenPoint(Math.round(bill.total_tokens / Math.max(bill.total_calls || 1, 1)));
      }
    } catch (_) { /* silent */ }
  }, 10000);
});

onUnmounted(() => {
  wsEvents.forEach(([event, fn]) => off(event, fn));
  wsEvents.length = 0;
  if (trendInterval) clearInterval(trendInterval);
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

/* Sparkline */
.chart-card { padding: 12px 16px; }
.sparkline { width: 100%; height: 60px; }
.trend-footer { display: flex; justify-content: space-between; margin-top: 8px; font-size: 0.8rem; color: var(--text2); }

/* Mini stats grid */
.grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.mini-stat { text-align: center; padding: 12px 0; }
.mini-stat .num { display: block; font-size: 1.6rem; font-weight: 700; }
.mini-stat .lbl { display: block; font-size: 0.8rem; color: var(--text2); margin-top: 2px; }
.mini-stat .num.green { color: #4ade80; }
.mini-stat .num.amber { color: #fbbf24; }
.mini-stat .num.blue { color: #38bdf8; }

/* Event log */
.event-log { max-height: 350px; overflow-y: auto; }
.event-log-actions { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; border-bottom: 1px solid var(--bg3); margin-bottom: 4px; }
.btn-small { background: var(--bg2); border: 1px solid var(--bg3); color: var(--text2); padding: 2px 10px; border-radius: 4px; cursor: pointer; font-size: 0.8rem; }
.btn-small:hover { background: var(--bg3); }
.event-row { display: flex; gap: 12px; padding: 5px 0; border-bottom: 1px solid var(--bg3); font-size: 0.85rem; align-items: center; }
.event-row:last-child { border-bottom: none; }
.event-time { color: var(--text2); font-family: monospace; min-width: 70px; flex-shrink: 0; }
.event-tag { padding: 1px 6px; border-radius: 3px; font-size: 0.75rem; font-weight: 600; min-width: 100px; text-align: center; }
.event-tag.ok { background: rgba(74,222,128,0.15); color: var(--green); }
.event-tag.err { background: rgba(248,113,113,0.15); color: var(--red); }
.event-tag.warn { background: rgba(251,191,36,0.15); color: var(--amber); }
.event-data { color: var(--text2); font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
