<template>
  <div>
    <div class="grid">
      <div class="card">
        <div class="card-title">已发布 (Published)</div>
        <div class="stat-value green">{{ published.length }}</div>
      </div>
      <div class="card">
        <div class="card-title">待审核</div>
        <div class="stat-value amber">{{ pending.length }}</div>
      </div>
      <div class="card">
        <div class="card-title">草稿</div>
        <div class="stat-value blue">{{ drafts.length }}</div>
      </div>
      <div class="card">
        <div class="card-title">已拒绝</div>
        <div class="stat-value red">{{ rejected.length }}</div>
      </div>
    </div>

    <!-- Publish New Skill -->
    <h3 class="section-title">📦 发布新技能</h3>
    <div class="card" style="margin-bottom:16px">
      <div class="publish-form">
        <input v-model="publishForm.name" placeholder="技能名称" class="form-input" />
        <select v-model="publishForm.type" class="form-input" style="max-width:150px">
          <option value="personality">Personality</option>
          <option value="agent">Agent</option>
          <option value="workflow">Workflow</option>
        </select>
        <input v-model="publishForm.author" placeholder="作者" class="form-input" style="max-width:150px" />
        <input v-model="publishForm.file" placeholder="文件路径 (可选)" class="form-input" style="flex:1" />
        <button class="btn btn-sm btn-accent" @click="publishSkill">发布</button>
      </div>
      <p v-if="publishMsg" :style="{ color: publishOk ? 'var(--green)' : 'var(--red)', marginTop: '8px', fontSize: '0.85rem' }">{{ publishMsg }}</p>
    </div>

    <!-- Pending Review -->
    <h3 class="section-title">🔍 待审核</h3>
    <div class="card" style="margin-bottom:16px">
      <table v-if="pending.length">
        <thead><tr><th>名称</th><th>版本</th><th>类型</th><th>作者</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="s in pending" :key="s.name + s.version">
            <td><strong>{{ s.name }}</strong></td>
            <td>{{ s.version }}</td>
            <td>{{ s.type }}</td>
            <td>{{ s.author || '-' }}</td>
            <td>
              <div class="action-btns">
                <button class="btn btn-xs btn-green" @click="approveSkill(s)">✔ 批准</button>
                <button class="btn btn-xs btn-red" @click="startReject(s)">✘ 拒绝</button>
              </div>
              <div v-if="rejectTarget?.name === s.name" class="reject-form" style="margin-top:6px">
                <input v-model="rejectReason" placeholder="拒绝原因" class="form-input" style="width:200px;font-size:0.8rem" />
                <button class="btn btn-xs btn-red" @click="rejectSkill(s)">确认拒绝</button>
                <button class="btn btn-xs" @click="cancelReject">取消</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else style="color:var(--text2);padding:12px;text-align:center">暂无待审核技能</p>
    </div>

    <!-- Drafts -->
    <h3 class="section-title">📝 草稿</h3>
    <div class="card" style="margin-bottom:16px">
      <table v-if="drafts.length">
        <thead><tr><th>名称</th><th>版本</th><th>类型</th><th>作者</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="s in drafts" :key="s.name + s.version">
            <td><strong>{{ s.name }}</strong></td>
            <td>{{ s.version }}</td>
            <td>{{ s.type }}</td>
            <td>{{ s.author || '-' }}</td>
            <td><button class="btn btn-xs btn-amber" @click="submitForReview(s)">提交审核</button></td>
          </tr>
        </tbody>
      </table>
      <p v-else style="color:var(--text2);padding:12px;text-align:center">暂无草稿</p>
    </div>

    <!-- Published -->
    <h3 class="section-title">✅ 已发布</h3>
    <div class="card">
      <table v-if="published.length">
        <thead><tr><th>名称</th><th>版本</th><th>类型</th><th>作者</th><th>标签</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="s in published" :key="s.name + s.version">
            <td><strong>{{ s.name }}</strong></td>
            <td>{{ s.version }}</td>
            <td>{{ s.type }}</td>
            <td>{{ s.author || '-' }}</td>
            <td><span v-for="t in s.tags" :key="t" class="tag info" style="margin-right:4px">{{ t }}</span></td>
            <td><button class="btn btn-xs btn-blue" @click="installSkill(s)">安装</button></td>
          </tr>
        </tbody>
      </table>
      <p v-else style="color:var(--text2);padding:12px;text-align:center">暂无已发布技能</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import { api } from '../api.js';

const all = ref([]);
const rejectTarget = ref(null);
const rejectReason = ref('');
const publishMsg = ref('');
const publishOk = ref(false);
const publishForm = ref({ name: '', type: 'personality', author: '', file: '' });

const published = computed(() => all.value.filter(s => s.status === 'published' || s.status === 'approved'));
const pending = computed(() => all.value.filter(s => s.status === 'pending_review' || s.status === 'in_review'));
const drafts = computed(() => all.value.filter(s => s.status === 'draft'));
const rejected = computed(() => all.value.filter(s => s.status === 'rejected'));

async function load() {
  try {
    const data = await api.skills('all');
    all.value = Array.isArray(data) ? data : (data.data || []);
  } catch (e) {
    console.error('Skills load error:', e);
  }
}

async function publishSkill() {
  try {
    const payload = { name: publishForm.value.name, type: publishForm.value.type, author: publishForm.value.author };
    if (publishForm.value.file) payload.file = publishForm.value.file;
    const result = await api.skillPublish(payload);
    publishMsg.value = `✅ 技能 "${result.name}" v${result.version} 已发布`;
    publishOk.value = true;
    await load();
  } catch (e) {
    publishMsg.value = `❌ 发布失败: ${e.message}`;
    publishOk.value = false;
  }
}

async function submitForReview(s) {
  try {
    const resp = await fetch(`/api/v1/skills/${s.name}/submit`, { method: 'POST' });
    if (resp.ok) await load();
    else alert(`提交失败: ${await resp.text()}`);
  } catch (e) {
    console.error(e);
  }
}

async function approveSkill(s) {
  try {
    const resp = await fetch(`/api/v1/skills/${s.name}/approve?reviewer=admin`, { method: 'POST' });
    if (resp.ok) await load();
    else alert(`审批失败: ${await resp.text()}`);
  } catch (e) {
    console.error(e);
  }
}

function startReject(s) { rejectTarget.value = s; rejectReason.value = ''; }
function cancelReject() { rejectTarget.value = null; rejectReason.value = ''; }

async function rejectSkill(s) {
  try {
    if (!rejectReason.value.trim()) { alert('请填写拒绝原因'); return; }
    const resp = await fetch(`/api/v1/skills/${s.name}/reject?reason=${encodeURIComponent(rejectReason.value)}`, { method: 'POST' });
    if (resp.ok) { cancelReject(); await load(); }
    else alert(`拒绝失败: ${await resp.text()}`);
  } catch (e) {
    console.error(e);
  }
}

async function installSkill(s) {
  try {
    const resp = await fetch(`/api/v1/skills/${s.name}/install`, { method: 'POST' });
    if (resp.ok) {
      const data = await resp.json();
      alert(`✅ 已安装到: ${data.path || data.detail || '本地'}`);
    } else {
      alert(`安装失败: ${await resp.text()}`);
    }
  } catch (e) {
    console.error(e);
  }
}

onMounted(load);
</script>

<style scoped>
.publish-form { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.form-input { background: var(--bg3); color: var(--text); border: 1px solid var(--bg3); border-radius: 6px; padding: 8px 12px; font-size: 0.9rem; }
.form-input:focus { outline: none; border-color: var(--accent); }
.action-btns { display: flex; gap: 4px; }
.btn-xs { padding: 2px 8px; font-size: 0.8rem; border: 1px solid var(--bg3); border-radius: 4px; cursor: pointer; background: var(--bg2); color: var(--text); }
.btn-xs:hover { filter: brightness(1.2); }
.btn-accent { background: var(--accent); color: var(--bg); border: none; padding: 8px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; }
.btn-accent:hover { filter: brightness(1.2); }
.btn-green { border-color: var(--green); color: var(--green); }
.btn-amber { border-color: var(--amber); color: var(--amber); }
.btn-blue { border-color: var(--accent); color: var(--accent); }
.btn-red { border-color: var(--red); color: var(--red); }
.reject-form { display: flex; gap: 4px; align-items: center; }
</style>
