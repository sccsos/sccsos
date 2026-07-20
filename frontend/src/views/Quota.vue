<template>
  <div>
    <!-- Usage Overview -->
    <div class="grid-2">
      <div class="card">
        <div class="card-title">📋 Agent 配额</div>
        <div style="margin-top:12px">
          <div class="row"><span>当前 / 最大 Agents</span><span>{{ quota?.current_agents }} / {{ quota?.max_agents }}</span></div>
          <div class="progress-bar"><div :class="['progress-fill', pct(agentPct)]" :style="{ width: agentPct + '%' }"></div></div>
          <div style="margin-top:16px">
            <div class="row"><span>Memory 条目</span><span>{{ quota?.memory_entries }} / {{ quota?.max_memory_entries }}</span></div>
            <div class="progress-bar"><div :class="['progress-fill', pct(memPct)]" :style="{ width: Math.min(memPct, 100) + '%' }"></div></div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">💰 费用配额</div>
        <div style="margin-top:12px">
          <div class="stat-value blue">${{ quota?.cost_today?.toFixed(4) }}</div>
          <div class="stat-label">今日已用 / ${{ quota?.max_cost_per_day?.toFixed(2) }} 日限额</div>
          <div class="progress-bar"><div :class="['progress-fill', pct(costDailyPct)]" :style="{ width: Math.min(costDailyPct, 100) + '%' }"></div></div>
          <div style="margin-top:16px">
            <div class="row"><span>累计费用</span><span>${{ quota?.cost_total?.toFixed(4) }} / ${{ quota?.max_cost_total?.toFixed(2) }}</span></div>
            <div class="progress-bar"><div :class="['progress-fill', pct(costTotalPct)]" :style="{ width: Math.min(costTotalPct, 100) + '%' }"></div></div>
          </div>
        </div>
      </div>
    </div>

    <div class="card" style="margin-bottom:16px">
      <div class="card-title">📊 Token 配额</div>
      <div style="margin-top:12px">
        <div class="stat-value purple">{{ (quota?.tokens_today || 0).toLocaleString() }}</div>
        <div class="stat-label">今日已用 / {{ (quota?.max_tokens_per_day || 0).toLocaleString() }} 日限额</div>
        <div class="progress-bar"><div :class="['progress-fill', pct(tokenPct)]" :style="{ width: Math.min(tokenPct, 100) + '%' }"></div></div>
      </div>
    </div>

    <!-- Configuration Panel -->
    <h3 class="section-title">⚙️ 配额配置</h3>
    <div class="card">
      <div class="config-grid">
        <div class="config-item">
          <label>最大 Agents</label>
          <input type="number" v-model.number="config.max_agents" class="form-input" />
        </div>
        <div class="config-item">
          <label>日 Token 上限</label>
          <input type="number" v-model.number="config.max_tokens_per_day" class="form-input" />
        </div>
        <div class="config-item">
          <label>日费用上限 ($)</label>
          <input type="number" step="0.01" v-model.number="config.max_cost_per_day" class="form-input" />
        </div>
        <div class="config-item">
          <label>总费用上限 ($)</label>
          <input type="number" step="0.01" v-model.number="config.max_cost_total" class="form-input" />
        </div>
        <div class="config-item">
          <label>Memory 条目上限</label>
          <input type="number" v-model.number="config.max_memory_entries" class="form-input" />
        </div>
        <div class="config-item config-actions">
          <button class="btn btn-accent" @click="saveConfig">💾 保存配置</button>
        </div>
      </div>
      <p v-if="configMsg" :style="{ color: configOk ? 'var(--green)' : 'var(--red)', marginTop: '8px', fontSize: '0.85rem' }">{{ configMsg }}</p>
    </div>

    <p v-if="!quota" class="loading">加载配额数据...</p>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue';
import { api } from '../api.js';

const quota = ref(null);
const config = reactive({
  max_agents: 10,
  max_tokens_per_day: 500000,
  max_cost_per_day: 10.0,
  max_cost_total: 100.0,
  max_memory_entries: 10000,
});
const configMsg = ref('');
const configOk = ref(false);

// Sync config from quota data
watch(quota, (q) => {
  if (!q) return;
  config.max_agents = q.max_agents;
  config.max_tokens_per_day = q.max_tokens_per_day;
  config.max_cost_per_day = q.max_cost_per_day;
  config.max_cost_total = q.max_cost_total;
  config.max_memory_entries = q.max_memory_entries;
}, { immediate: true });

const agentPct = computed(() => pctVal(quota.value?.current_agents, quota.value?.max_agents));
const memPct = computed(() => pctVal(quota.value?.memory_entries, quota.value?.max_memory_entries));
const tokenPct = computed(() => pctVal(quota.value?.tokens_today, quota.value?.max_tokens_per_day));
const costDailyPct = computed(() => pctVal(quota.value?.cost_today, quota.value?.max_cost_per_day));
const costTotalPct = computed(() => pctVal(quota.value?.cost_total, quota.value?.max_cost_total));

function pctVal(current, max) {
  if (!max || max === 0) return 0;
  return Math.round((current || 0) / max * 100);
}
function pct(v) {
  if (v > 80) return 'red';
  if (v > 50) return 'amber';
  return 'green';
}

async function saveConfig() {
  configMsg.value = '';
  try {
    const resp = await fetch('/api/v1/quotas/default', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    await loadQuota();
    configMsg.value = '✅ 配额配置已保存';
    configOk.value = true;
  } catch (e) {
    configMsg.value = `❌ 保存失败: ${e.message}`;
    configOk.value = false;
  }
}

async function loadQuota() {
  try { quota.value = await api.quota(); }
  catch (e) { console.error(e); }
}

onMounted(loadQuota);
</script>

<style scoped>
.config-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
.config-item { display: flex; flex-direction: column; gap: 4px; }
.config-item label { font-size: 0.8rem; color: var(--text2); }
.config-actions { display: flex; align-items: flex-end; }
.form-input { background: var(--bg3); color: var(--text); border: 1px solid var(--bg3); border-radius: 6px; padding: 8px 12px; font-size: 0.9rem; }
.form-input:focus { outline: none; border-color: var(--accent); }
.btn-accent { background: var(--accent); color: var(--bg); border: none; padding: 8px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; }
.btn-accent:hover { filter: brightness(1.2); }
</style>
