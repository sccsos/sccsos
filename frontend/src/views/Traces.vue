<template>
  <div>
    <div class="card">
      <div class="card-header">
        <div class="card-title">🔄 追踪记录</div>
        <div class="filter-bar">
          <select v-model="statusFilter" @change="load" class="filter-select">
            <option value="">全部状态</option>
            <option value="ok">成功</option>
            <option value="error">失败</option>
            <option value="running">运行中</option>
          </select>
        </div>
      </div>

      <table v-if="filtered.length">
        <thead>
          <tr>
            <th>Trace ID</th><th>名称</th><th>Agent</th><th>状态</th><th>步骤</th><th>耗时</th><th>开始时间</th><th></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="t in filtered" :key="t.trace_id || t.id">
            <tr class="trace-row" @click="toggleDetail(t)">
              <td style="font-family:monospace;font-size:0.8rem;color:var(--text2)">
                {{ (t.trace_id || t.id || '').slice(0, 12) }}
              </td>
              <td>{{ t.name || '-' }}</td>
              <td>{{ t.agent_name || '-' }}</td>
              <td><span :class="['tag', statusClass(t)]">{{ t.status || '?' }}</span></td>
              <td>{{ t.span_count || t.spans?.length || '-' }}</td>
              <td>{{ t.duration_ms ? (t.duration_ms / 1000).toFixed(1) + 's' : '-' }}</td>
              <td style="font-size:0.8rem;color:var(--text2)">{{ formatTime(t.start_time) }}</td>
              <td><span class="expand-icon">{{ expandedTraces[t.trace_id || t.id] ? '▼' : '▶' }}</span></td>
            </tr>
            <tr v-if="expandedTraces[t.trace_id || t.id]" class="detail-row">
              <td colspan="8">
                <div class="trace-detail">
                  <div v-if="t.spans?.length">
                    <div v-for="span in t.spans" :key="span.span_id" class="span-row" :style="{ marginLeft: (span.depth || 0) * 20 + 'px' }">
                      <span :class="['span-status', spanClass(span)]">{{ span.status || 'ok' }}</span>
                      <span class="span-name">{{ span.name || span.operation || 'step' }}</span>
                      <span class="span-time">{{ span.duration_ms ? (span.duration_ms + 'ms') : '-' }}</span>
                    </div>
                  </div>
                  <div v-else style="color:var(--text2)">无详细 span 数据</div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <p v-else class="loading">{{ loading ? '加载中...' : '暂无追踪记录' }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { api } from '../api.js';
import { useWS } from '../ws.js';

const traces = ref([]);
const loading = ref(false);
const statusFilter = ref('');
const expandedTraces = ref({});

const { on, off } = useWS();

function statusClass(t) {
  if (t.status === 'ok' || t.status === 'success') return 'ok';
  if (t.status === 'error' || t.status === 'failed') return 'err';
  return 'warn';
}

function spanClass(s) {
  if (s.status === 'ok' || s.status === 'success') return 'ok';
  if (s.status === 'error' || s.status === 'failed') return 'err';
  return 'warn';
}

function formatTime(ts) {
  if (!ts) return '-';
  return ts.slice(0, 19).replace('T', ' ');
}

const filtered = computed(() => {
  if (!statusFilter.value) return traces.value;
  return traces.value.filter(t => t.status === statusFilter.value);
});

function toggleDetail(t) {
  const id = t.trace_id || t.id;
  expandedTraces.value = { ...expandedTraces.value, [id]: !expandedTraces.value[id] };
}

async function load() {
  loading.value = true;
  try {
    const data = await api.traces(50);
    traces.value = Array.isArray(data) ? data : (data.data || []);
  } catch (e) {
    console.error('Traces load error:', e);
  } finally {
    loading.value = false;
  }
}

// Auto-refresh on workflow events
on('workflow.completed', () => setTimeout(load, 1000));
on('workflow.failed', () => setTimeout(load, 1000));

onMounted(load);
onUnmounted(() => { off('workflow.completed', load); off('workflow.failed', load); });
</script>

<style scoped>
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.filter-bar { display: flex; gap: 8px; }
.filter-select { background: var(--bg3); color: var(--text); border: 1px solid var(--bg3); border-radius: 6px; padding: 6px 12px; font-size: 0.85rem; }
.trace-row { cursor: pointer; }
.trace-row:hover { background: rgba(56,189,248,0.05); }
.expand-icon { color: var(--text2); font-size: 0.75rem; }
.detail-row td { padding: 0; }
.trace-detail { background: var(--bg3); padding: 12px 20px; margin: 0; }
.span-row { display: flex; gap: 12px; padding: 4px 0; font-size: 0.85rem; align-items: center; }
.span-status { padding: 1px 6px; border-radius: 3px; font-size: 0.7rem; font-weight: 600; min-width: 40px; text-align: center; }
.span-status.ok { background: rgba(74,222,128,0.15); color: var(--green); }
.span-status.err { background: rgba(248,113,113,0.15); color: var(--red); }
.span-status.warn { background: rgba(251,191,36,0.15); color: var(--amber); }
.span-name { flex: 1; }
.span-time { color: var(--text2); font-family: monospace; }
</style>
