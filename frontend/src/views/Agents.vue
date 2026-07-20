<template>
  <div>
    <div class="grid">
      <div class="card">
        <div class="card-title">总计</div>
        <div class="stat-value blue">{{ agentsStore.count }}</div>
        <div class="stat-label">已注册 Agent</div>
      </div>
      <div class="card">
        <div class="card-title">运行中</div>
        <div class="stat-value green">{{ agentsStore.running.length }}</div>
      </div>
      <div class="card">
        <div class="card-title">失败</div>
        <div class="stat-value red">{{ agentsStore.failed.length }}</div>
      </div>
    </div>

    <div class="card">
      <table>
        <thead>
          <tr>
            <th>名称</th><th>状态</th><th>租户</th><th>版本</th><th>Token 用量</th><th>错误</th><th>创建时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in agentsStore.items" :key="a.id">
            <td><strong>{{ a.name || a.id }}</strong></td>
            <td><span :class="['tag', statusClass(a.status)]">{{ statusLabel(a.status) }}</span></td>
            <td>{{ a.tenant_id || 'default' }}</td>
            <td>{{ a.spec_version || '-' }}</td>
            <td>{{ (a.total_tokens || 0).toLocaleString() }}</td>
            <td>{{ a.error_count || 0 }}</td>
            <td style="font-size:0.8rem;color:var(--text2)">{{ a.created_at?.slice(0, 10) || '-' }}</td>
            <td>
              <div class="action-btns">
                <button v-if="canStart(a.status)" class="btn btn-xs btn-green" @click="doAction(a.name, 'start')" :disabled="a._loading">▶</button>
                <button v-if="canPause(a.status)" class="btn btn-xs btn-amber" @click="doAction(a.name, 'pause')" :disabled="a._loading">⏸</button>
                <button v-if="canResume(a.status)" class="btn btn-xs btn-blue" @click="doAction(a.name, 'resume')" :disabled="a._loading">▶</button>
                <button v-if="canStop(a.status)" class="btn btn-xs btn-red" @click="doAction(a.name, 'stop')" :disabled="a._loading">⏹</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!agentsStore.items.length" style="color:var(--text2);padding:20px;text-align:center">暂无 Agent 数据</p>
      <p v-if="agentsStore.loading" style="color:var(--text2);padding:8px;text-align:center">加载中...</p>
      <p v-if="agentsStore.error" style="color:var(--red);padding:8px;text-align:center">{{ agentsStore.error }}</p>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue';
import { useAgentsStore } from '../stores/agents.js';

const agentsStore = useAgentsStore();

function statusClass(s) {
  if (s === 'running') return 'ok';
  if (s === 'failed') return 'err';
  if (s === 'paused') return 'warn';
  return 'warn';
}

function statusLabel(s) {
  const labels = { running: '运行中', paused: '已暂停', failed: '失败', created: '已创建', terminated: '已终止' };
  return labels[s] || s;
}

function canStart(s) { return s === 'created' || s === 'terminated' || s === 'failed'; }
function canPause(s) { return s === 'running'; }
function canResume(s) { return s === 'paused'; }
function canStop(s) { return s === 'running' || s === 'paused'; }

async function doAction(name, action) {
  try {
    await agentsStore.action(name, action);
  } catch (e) {
    console.error(`Agent ${action} failed:`, e);
  }
}

onMounted(() => agentsStore.fetch());
</script>

<style scoped>
.action-btns { display: flex; gap: 4px; }
.btn-xs { padding: 2px 8px; font-size: 0.8rem; border: 1px solid var(--bg3); border-radius: 4px; cursor: pointer; background: var(--bg2); color: var(--text); }
.btn-xs:hover { filter: brightness(1.2); }
.btn-xs:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-green { border-color: var(--green); color: var(--green); }
.btn-amber { border-color: var(--amber); color: var(--amber); }
.btn-blue { border-color: var(--accent); color: var(--accent); }
.btn-red { border-color: var(--red); color: var(--red); }
</style>
