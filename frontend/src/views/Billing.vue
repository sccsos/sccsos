<template>
  <div>
    <!-- Filters -->
    <div class="card" style="margin-bottom:16px">
      <div class="form-row">
        <div class="form-group">
          <label>开始日期</label>
          <input type="date" v-model="startDate" @change="load" />
        </div>
        <div class="form-group">
          <label>结束日期</label>
          <input type="date" v-model="endDate" @change="load" />
        </div>
        <div class="form-group">
          <label>租户</label>
          <input type="text" v-model="tenant" placeholder="default" @change="load" />
        </div>
        <div class="form-group" style="align-self:flex-end">
          <button class="btn btn-sm btn-accent" @click="downloadCSV">⬇ CSV 下载</button>
        </div>
      </div>
    </div>

    <!-- Summary Cards -->
    <div class="grid" v-if="summary">
      <div class="card">
        <div class="card-title">调用次数</div>
        <div class="stat-value blue">{{ summary.total_calls }}</div>
      </div>
      <div class="card">
        <div class="card-title">Token 总量</div>
        <div class="stat-value purple">{{ summary.total_tokens?.toLocaleString() }}</div>
      </div>
      <div class="card">
        <div class="card-title">总费用</div>
        <div class="stat-value amber">${{ summary.total_cost?.toFixed(4) }}</div>
      </div>
      <div class="card">
        <div class="card-title">总时长</div>
        <div class="stat-value green">{{ (summary.total_duration_ms / 1000).toFixed(1) }}s</div>
      </div>
    </div>

    <div class="grid-2" v-if="summary">
      <!-- By Model -->
      <div class="card">
        <div class="card-title">按模型</div>
        <div v-for="(cost, model) in sortedByModel" :key="model" class="row">
          <span>{{ model }}</span><span>${{ cost.toFixed(4) }}</span>
          <div class="bar-mini" :style="{ width: (cost / maxModelCost * 100) + '%' }"></div>
        </div>
        <p v-if="!modelCount" style="color:var(--text2);padding:8px">暂无数据</p>
      </div>

      <!-- By Agent -->
      <div class="card">
        <div class="card-title">按 Agent</div>
        <div v-for="(cost, agent) in sortedByAgent" :key="agent" class="row">
          <span>{{ agent }}</span><span>${{ cost.toFixed(4) }}</span>
          <div class="bar-mini" :style="{ width: (cost / maxAgentCost * 100) + '%' }"></div>
        </div>
        <p v-if="!agentCount" style="color:var(--text2);padding:8px">暂无数据</p>
      </div>
    </div>

    <!-- Daily Cost Table -->
    <h3 class="section-title">📅 每日费用</h3>
    <div class="card" v-if="summary?.by_day">
      <table>
        <thead><tr><th>日期</th><th>费用</th><th>趋势</th></tr></thead>
        <tbody>
          <tr v-for="(cost, day) in sortedByDay" :key="day">
            <td>{{ day }}</td>
            <td>${{ cost.toFixed(4) }}</td>
            <td><div class="bar" :style="{ width: (cost / maxDayCost * 100) + '%' }"></div></td>
          </tr>
        </tbody>
      </table>
      <p v-if="!dayCount" style="color:var(--text2);padding:8px">暂无数据</p>
    </div>

    <!-- Tool Usage -->
    <h3 class="section-title">🔧 工具调用</h3>
    <div class="card" v-if="summary?.by_tool">
      <table>
        <thead><tr><th>工具</th><th>调用次数</th></tr></thead>
        <tbody>
          <tr v-for="(count, tool) in sortedByTool" :key="tool">
            <td>{{ tool }}</td>
            <td>{{ count }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!toolCount" style="color:var(--text2);padding:8px">暂无数据</p>
    </div>

    <p v-if="!summary" class="loading">选择日期范围后查看计费数据</p>

    <p v-if="downloadMsg" :style="{ color: downloadOk ? 'var(--green)' : 'var(--red)', marginTop: '8px', fontSize: '0.85rem' }">{{ downloadMsg }}</p>

    <!-- ── Subscription Plan Management ────────────────────────── -->
    <h3 class="section-title" style="margin-top:24px">📋 计费方案</h3>
    <div class="card">
      <div class="form-row">
        <div class="form-group">
          <label>租户 ID</label>
          <input type="text" v-model="planForm.tenant_id" placeholder="default" />
        </div>
        <div class="form-group">
          <label>计费模式</label>
          <select v-model="planForm.tier" class="form-select">
            <option value="pay_per_token">按 Token (pay_per_token)</option>
            <option value="per_call">按调用 (per_call)</option>
            <option value="subscription">月度订阅 (subscription)</option>
          </select>
        </div>
        <div class="form-group" v-if="planForm.tier === 'subscription'">
          <label>月费 ($)</label>
          <input type="number" v-model.number="planForm.monthly_fee" step="1" min="0" />
        </div>
        <div class="form-group" v-if="planForm.tier === 'per_call'">
          <label>每次调用费 ($)</label>
          <input type="number" v-model.number="planForm.flat_fee_per_call" step="0.001" min="0" />
        </div>
      </div>

      <div class="form-row" style="margin-top:8px">
        <div class="form-group" style="flex:1">
          <label>模型费率 (JSON: { \"model\": rate_per_1M })</label>
          <input type="text" v-model="planForm.modelRatesStr" placeholder='{"deepseek": 0.002, "gpt-4": 0.03}' class="form-input-wide" />
        </div>
        <div class="form-group" style="align-self:flex-end">
          <label style="visibility:hidden">.</label>
          <label class="checkbox-label">
            <input type="checkbox" v-model="planForm.active" /> 激活
          </label>
        </div>
      </div>

      <div class="form-actions" style="margin-top:12px">
        <button class="btn btn-sm btn-accent" @click="savePlan">💾 保存方案</button>
        <button class="btn btn-sm btn-outline" @click="loadPlan" style="margin-left:8px">🔄 加载</button>
        <button class="btn btn-sm btn-danger" @click="resetPlan" style="margin-left:8px">🗑 重置</button>
      </div>
      <p v-if="planMsg" :style="{ color: planOk ? 'var(--green)' : 'var(--red)', marginTop: '8px', fontSize: '0.85rem' }">{{ planMsg }}</p>
    </div>

    <!-- Existing Plans -->
    <div class="card" style="margin-top:8px" v-if="plans.length > 0">
      <div class="card-title">已配置方案</div>
      <table>
        <thead><tr><th>租户</th><th>模式</th><th>月费</th><th>调用费</th><th>模型费率</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="p in plans" :key="p.tenant_id" @click="editPlan(p)" style="cursor:pointer">
            <td>{{ p.tenant_id }}</td>
            <td><span class="tier-badge">{{ p.tier }}</span></td>
            <td>{{ p.tier === 'subscription' ? '$' + p.monthly_fee : '-' }}</td>
            <td>{{ p.tier === 'per_call' ? '$' + p.flat_fee_per_call : '-' }}</td>
            <td style="font-size:0.8rem">{{ Object.keys(p.model_rates || {}).slice(0,3).join(', ') }}{{ Object.keys(p.model_rates || {}).length > 3 ? '...' : '' }}</td>
            <td>{{ p.active ? '✅' : '⛔' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import { api } from '../api.js';

const today = new Date().toISOString().slice(0, 10);
const startDate = ref(today);
const endDate = ref(today);
const tenant = ref('');
const summary = ref(null);
const downloadMsg = ref('');
const downloadOk = ref(false);

// Subscription plan management
const plans = ref([]);
const planMsg = ref('');
const planOk = ref(false);
const planForm = ref({
  tenant_id: 'default',
  tier: 'pay_per_token',
  monthly_fee: 0,
  flat_fee_per_call: 0.01,
  modelRatesStr: '{}',
  active: true,
});

function planToForm(p) {
  planForm.value.tenant_id = p.tenant_id || 'default';
  planForm.value.tier = p.tier || 'pay_per_token';
  planForm.value.monthly_fee = p.monthly_fee || 0;
  planForm.value.flat_fee_per_call = p.flat_fee_per_call || 0.01;
  planForm.value.modelRatesStr = JSON.stringify(p.model_rates || {}, null, 0);
  planForm.value.active = p.active !== false;
}

async function loadPlans() {
  try {
    const resp = await api.billingPlans();
    plans.value = resp.plans || [];
  } catch (e) {
    plans.value = [];
  }
}

async function loadPlan() {
  try {
    const tid = planForm.value.tenant_id || 'default';
    const p = await api.billingPlanGet(tid);
    planToForm(p);
    planMsg.value = `✅ 已加载 ${tid} 的方案`;
    planOk.value = true;
  } catch (e) {
    planMsg.value = `❌ 加载失败: ${e.message}`;
    planOk.value = false;
  }
}

async function savePlan() {
  try {
    let modelRates = {};
    try {
      modelRates = JSON.parse(planForm.value.modelRatesStr || '{}');
    } catch {
      planMsg.value = '❌ 模型费率 JSON 格式错误';
      planOk.value = false;
      return;
    }
    const data = {
      tenant_id: planForm.value.tenant_id || 'default',
      tier: planForm.value.tier,
      monthly_fee: planForm.value.monthly_fee || 0,
      flat_fee_per_call: planForm.value.flat_fee_per_call || 0.01,
      model_rates: modelRates,
      active: planForm.value.active,
    };
    const resp = await api.billingPlanSet(data);
    planMsg.value = `✅ ${resp.tenant_id} 方案已更新 (${resp.tier})`;
    planOk.value = true;
    await loadPlans();
  } catch (e) {
    planMsg.value = `❌ 保存失败: ${e.message}`;
    planOk.value = false;
  }
}

async function resetPlan() {
  try {
    const tid = planForm.value.tenant_id || 'default';
    await api.billingPlanReset(tid);
    planMsg.value = `✅ ${tid} 方案已重置`;
    planOk.value = true;
    planToForm({ tenant_id: tid });
    await loadPlans();
  } catch (e) {
    planMsg.value = `❌ 重置失败: ${e.message}`;
    planOk.value = false;
  }
}

function editPlan(p) {
  planToForm(p);
}

const modelCount = computed(() => Object.keys(summary.value?.by_model || {}).length);
const agentCount = computed(() => Object.keys(summary.value?.by_agent || {}).length);
const dayCount = computed(() => Object.keys(summary.value?.by_day || {}).length);
const toolCount = computed(() => Object.keys(summary.value?.by_tool || {}).length);

const maxModelCost = computed(() => Math.max(...Object.values(summary.value?.by_model || {0: 0.001}), 0.001));
const maxAgentCost = computed(() => Math.max(...Object.values(summary.value?.by_agent || {0: 0.001}), 0.001));
const maxDayCost = computed(() => Math.max(...Object.values(summary.value?.by_day || {0: 0.001}), 0.001));

const sortedByModel = computed(() => {
  const m = summary.value?.by_model || {};
  return Object.entries(m).sort((a, b) => b[1] - a[1]);
});

const sortedByAgent = computed(() => {
  const m = summary.value?.by_agent || {};
  return Object.entries(m).sort((a, b) => b[1] - a[1]);
});

const sortedByDay = computed(() => {
  const m = summary.value?.by_day || {};
  return Object.entries(m).sort((a, b) => a[0].localeCompare(b[0]));
});

const sortedByTool = computed(() => {
  const m = summary.value?.by_tool || {};
  return Object.entries(m).sort((a, b) => b[1] - a[1]);
});

async function load() {
  try {
    summary.value = await api.billingSummary(
      startDate.value,
      endDate.value,
      tenant.value || undefined
    );
  } catch (e) {
    console.error(e);
    summary.value = null;
  }
}

async function downloadCSV() {
  try {
    const params = new URLSearchParams({ start: startDate.value, end: endDate.value });
    if (tenant.value) params.set('tenant', tenant.value);
    const resp = await fetch(`/api/v1/billing/export?${params}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `billing_${startDate.value}_${endDate.value}${tenant.value ? '_' + tenant.value : ''}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    downloadMsg.value = `✅ CSV 已下载 (${(blob.size / 1024).toFixed(1)} KB)`;
    downloadOk.value = true;
  } catch (e) {
    downloadMsg.value = `❌ 下载失败: ${e.message}`;
    downloadOk.value = false;
  }
}

onMounted(() => {
  load();
  loadPlans();
});
</script>

<style scoped>
.form-row { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-end; }
.form-group { display: flex; flex-direction: column; gap: 4px; }
.form-group label { font-size: 0.8rem; color: var(--text2); text-transform: uppercase; letter-spacing: 0.05em; }
.form-group input { background: var(--bg3); color: var(--text); border: 1px solid var(--bg3); border-radius: 6px; padding: 8px 12px; font-size: 0.9rem; }
.form-group input:focus { outline: none; border-color: var(--accent); }
.bar { height: 8px; background: var(--accent); border-radius: 4px; min-width: 4px; max-width: 300px; }
.bar-mini { height: 4px; background: var(--accent); border-radius: 2px; margin-top: 2px; min-width: 4px; }
.btn-accent { background: var(--accent); color: var(--bg); border: none; padding: 8px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; }
.btn-accent:hover { filter: brightness(1.2); }
.btn-outline { background: transparent; color: var(--accent); border: 1px solid var(--accent); padding: 8px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; }
.btn-outline:hover { background: var(--accent); color: var(--bg); }
.btn-danger { background: var(--red, #e74c3c); color: #fff; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; }
.form-select { background: var(--bg3); color: var(--text); border: 1px solid var(--bg3); border-radius: 6px; padding: 8px 12px; font-size: 0.9rem; }
.form-select:focus { outline: none; border-color: var(--accent); }
.form-input-wide { background: var(--bg3); color: var(--text); border: 1px solid var(--bg3); border-radius: 6px; padding: 8px 12px; font-size: 0.85rem; width: 100%; box-sizing: border-box; }
.form-input-wide:focus { outline: none; border-color: var(--accent); }
.checkbox-label { display: flex; align-items: center; gap: 6px; font-size: 0.9rem; cursor: pointer; }
.tier-badge { background: var(--accent); color: var(--bg); padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }

</style>
