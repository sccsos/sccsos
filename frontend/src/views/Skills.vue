<template>
  <div>
    <!-- Stats cards -->
    <div class="grid">
      <div class="card">
        <div class="card-title">📦 技能市场</div>
        <div class="stat-value green">{{ published.length }}</div>
      </div>
      <div class="card">
        <div class="card-title">🔍 待审核</div>
        <div class="stat-value amber">{{ pending.length }}</div>
      </div>
      <div class="card">
        <div class="card-title">📝 草稿</div>
        <div class="stat-value blue">{{ drafts.length }}</div>
      </div>
      <div class="card">
        <div class="card-title">📋 已安装</div>
        <div class="stat-value cyan">{{ installed.length }}</div>
      </div>
    </div>

    <!-- Tab navigation -->
    <div class="tab-bar">
      <button v-for="tab in tabs" :key="tab.id" class="tab-btn"
              :class="{ active: activeTab === tab.id }"
              @click="activeTab = tab.id">
        {{ tab.label }}
      </button>
    </div>

    <!-- Tab: Market Browse -->
    <div v-if="activeTab === 'market'">
      <div class="card">
        <div class="search-bar">
          <input v-model="searchQuery" placeholder="🔍 搜索技能名称或描述..."
                 class="form-input search-input" @input="debounceSearch" />
          <select v-model="filterType" class="form-input filter-select" @change="loadMarket">
            <option value="">全部类型</option>
            <option value="personality">Personality</option>
            <option value="agent">Agent</option>
            <option value="workflow">Workflow</option>
          </select>
        </div>
      </div>

      <div class="card" style="margin-bottom:16px">
        <table v-if="published.length">
          <thead>
            <tr>
              <th>名称</th>
              <th>版本</th>
              <th>类型</th>
              <th>作者</th>
              <th>标签</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in filteredPublished" :key="s.name + s.version">
              <td><strong>{{ s.name }}</strong><br/><span class="desc">{{ s.description || '-' }}</span></td>
              <td>{{ s.version }}</td>
              <td><span class="tag" :class="s.type">{{ s.type }}</span></td>
              <td>{{ s.author || '-' }}</td>
              <td>
                <span v-for="t in (s.tags || [])" :key="t" class="tag info" style="margin-right:4px">{{ t }}</span>
              </td>
              <td>
                <button v-if="!isInstalled(s.name)" class="btn btn-xs btn-blue" @click="installSkill(s)">安装</button>
                <span v-else class="installed-badge">✅ 已装</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else style="color:var(--text2);padding:12px;text-align:center">
          {{ searchQuery ? '没有匹配的技能' : '暂无已发布技能' }}
        </p>
      </div>
    </div>

    <!-- Tab: Installed -->
    <div v-if="activeTab === 'installed'">
      <h3 class="section-title">📋 已安装技能</h3>
      <div class="card">
        <table v-if="installed.length">
          <thead><tr><th>名称</th><th>版本</th><th>类型</th><th>安装时间</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="s in installed" :key="s.name">
              <td><strong>{{ s.name }}</strong></td>
              <td>{{ s.version }}</td>
              <td>{{ s.type }}</td>
              <td>{{ s.installed_at ? s.installed_at.slice(0, 10) : '-' }}</td>
              <td><button class="btn btn-xs btn-red" @click="removeSkill(s)">卸载</button></td>
            </tr>
          </tbody>
        </table>
        <p v-else style="color:var(--text2);padding:12px;text-align:center">暂无已安装技能</p>
      </div>
    </div>

    <!-- Tab: Publish -->
    <div v-if="activeTab === 'publish'">
      <h3 class="section-title">📦 发布新技能</h3>
      <div class="card" style="margin-bottom:16px">
        <div class="publish-form">
          <input v-model="publishForm.name" placeholder="技能名称 *" class="form-input" />
          <select v-model="publishForm.type" class="form-input" style="max-width:150px">
            <option value="personality">Personality</option>
            <option value="agent">Agent</option>
            <option value="workflow">Workflow</option>
          </select>
          <input v-model="publishForm.author" placeholder="作者" class="form-input" style="max-width:150px" />
          <input v-model="publishForm.tags" placeholder="标签 (逗号分隔)" class="form-input" style="max-width:200px" />
          <label class="checkbox-label">
            <input type="checkbox" v-model="publishForm.autoApprove" /> 跳过审核
          </label>
          <button class="btn btn-sm btn-accent" @click="publishSkill">发布</button>
        </div>
        <textarea v-model="publishForm.content" placeholder="YAML 内容（可选，不填则仅注册元信息）"
                  class="form-textarea" rows="4"></textarea>
        <p v-if="publishMsg" :style="{ color: publishOk ? 'var(--green)' : 'var(--red)', marginTop: '8px', fontSize: '0.85rem' }">{{ publishMsg }}</p>
      </div>
    </div>

    <!-- Tab: Review -->
    <div v-if="activeTab === 'review'">
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

      <h3 class="section-title">📝 草稿</h3>
      <div class="card">
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
    </div>

    <!-- Tab: Popular -->
    <div v-if="activeTab === 'popular'">
      <div class="grid-2-col">
        <div class="card">
          <div class="card-title">⭐ 评分最高</div>
          <table v-if="topRated.length">
            <thead><tr><th>名称</th><th>评分</th><th>评价数</th><th>安装</th></tr></thead>
            <tbody>
              <tr v-for="s in topRated" :key="s.name">
                <td><strong>{{ s.name }}</strong><br/><span class="desc">{{ s.description || '-' }}</span></td>
                <td><span class="stars">{{ renderStars(s.avg_score) }}</span> {{ s.avg_score.toFixed(1) }}</td>
                <td>{{ s.total_ratings }}</td>
                <td>{{ s.install_count }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else style="color:var(--text2);padding:8px;text-align:center">暂无评分数据</p>
        </div>
        <div class="card">
          <div class="card-title">📥 安装最多</div>
          <table v-if="mostInstalled.length">
            <thead><tr><th>名称</th><th>安装数</th><th>类型</th><th>作者</th></tr></thead>
            <tbody>
              <tr v-for="s in mostInstalled" :key="s.name">
                <td><strong>{{ s.name }}</strong><br/><span class="desc">{{ s.description || '-' }}</span></td>
                <td><strong>{{ s.install_count }}</strong></td>
                <td><span class="tag" :class="s.type">{{ s.type }}</span></td>
                <td>{{ s.author || '-' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else style="color:var(--text2);padding:8px;text-align:center">暂无安装数据</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import { api } from '../api.js';

const tabs = [
  { id: 'popular', label: '🔥 热门' },
  { id: 'market', label: '🏪 市场浏览' },
  { id: 'installed', label: '📋 已安装' },
  { id: 'publish', label: '📦 发布' },
  { id: 'review', label: '🔍 审核' },
];
const activeTab = ref('popular');

const all = ref([]);
const installed = ref([]);
const searchQuery = ref('');
const filterType = ref('');
const rejectTarget = ref(null);
const rejectReason = ref('');
const publishMsg = ref('');
const publishOk = ref(false);
const publishForm = ref({ name: '', type: 'personality', author: '', tags: '', content: '', autoApprove: false });
const topRated = ref([]);
const mostInstalled = ref([]);

const published = computed(() => all.value.filter(s => s.status === 'published' || s.status === 'approved'));
const pending = computed(() => all.value.filter(s => s.status === 'pending_review' || s.status === 'in_review'));
const drafts = computed(() => all.value.filter(s => s.status === 'draft'));

const filteredPublished = computed(() => {
  let items = published.value;
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase();
    items = items.filter(s =>
      s.name.toLowerCase().includes(q) ||
      (s.description || '').toLowerCase().includes(q) ||
      (s.tags || []).some(t => t.toLowerCase().includes(q))
    );
  }
  if (filterType.value) {
    items = items.filter(s => s.type === filterType.value);
  }
  return items;
});

function isInstalled(name) {
  return installed.value.some(s => s.name === name);
}

let searchTimer = null;
function debounceSearch() {
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {}, 200);
}

async function loadAll() {
  try {
    all.value = await api.skills({ status: 'all' });
  } catch (e) { console.error('Skills load error:', e); }
}

async function loadInstalled() {
  try {
    installed.value = await api.skillsInstalled();
  } catch (e) { console.error('Installed load error:', e); }
}

function loadMarket() {
  // Uses the same all.value with client-side filtering
}

async function loadPopular() {
  try {
    topRated.value = await api.skillTopRated(10);
    mostInstalled.value = await api.skillMostInstalled(10);
  } catch (e) { console.error('Popular load error:', e); }
}

function renderStars(score) {
  const full = Math.round(score);
  return '★'.repeat(full) + '☆'.repeat(5 - full);
}

async function publishSkill() {
  if (!publishForm.value.name.trim()) {
    publishMsg.value = '❌ 技能名称不能为空';
    publishOk.value = false;
    return;
  }
  try {
    const result = await api.skillPublish({
      name: publishForm.value.name.trim(),
      type: publishForm.value.type,
      author: publishForm.value.author.trim(),
      tags: publishForm.value.tags.trim(),
      content: publishForm.value.content.trim(),
      auto_approve: publishForm.value.autoApprove,
    });
    publishMsg.value = `✅ 技能 "${result.name}" v${result.version} 已${result.status === 'published' ? '发布' : '创建为草稿'}`;
    publishOk.value = true;
    publishForm.value = { name: '', type: 'personality', author: '', tags: '', content: '', autoApprove: false };
    await loadAll();
  } catch (e) {
    publishMsg.value = `❌ 发布失败: ${e.message}`;
    publishOk.value = false;
  }
}

async function installSkill(s) {
  try {
    const result = await api.skillInstall(s.name);
    await loadInstalled();
    alert(`✅ 已安装到: ${result.path}`);
  } catch (e) {
    alert(`❌ 安装失败: ${e.message}`);
  }
}

async function removeSkill(s) {
  if (!confirm(`确定卸载技能 "${s.name}"？`)) return;
  try {
    await api.skillRemove(s.name);
    await loadInstalled();
  } catch (e) {
    console.error(e);
  }
}

async function submitForReview(s) {
  try {
    await api.skillSubmitReview(s.name);
    await loadAll();
  } catch (e) {
    alert(`提交失败: ${e.message}`);
  }
}

async function approveSkill(s) {
  try {
    await api.skillApprove(s.name);
    await loadAll();
  } catch (e) {
    alert(`审批失败: ${e.message}`);
  }
}

function startReject(s) { rejectTarget.value = s; rejectReason.value = ''; }
function cancelReject() { rejectTarget.value = null; rejectReason.value = ''; }

async function rejectSkill(s) {
  if (!rejectReason.value.trim()) { alert('请填写拒绝原因'); return; }
  try {
    await api.skillReject(s.name, rejectReason.value);
    cancelReject();
    await loadAll();
  } catch (e) {
    alert(`拒绝失败: ${e.message}`);
  }
}

onMounted(() => {
  loadAll();
  loadInstalled();
  loadPopular();
});
</script>

<style scoped>
.tab-bar { display: flex; gap: 4px; margin-bottom: 16px; flex-wrap: wrap; }
.tab-btn { padding: 8px 16px; border: 1px solid var(--bg3); border-radius: 8px; background: var(--bg2); color: var(--text2); cursor: pointer; font-size: 0.9rem; }
.tab-btn.active { background: var(--accent); color: var(--bg); border-color: var(--accent); font-weight: 600; }
.tab-btn:hover:not(.active) { filter: brightness(1.2); }

.search-bar { display: flex; gap: 8px; align-items: center; }
.search-input { flex: 1; }
.filter-select { max-width: 160px; }
.form-input { background: var(--bg3); color: var(--text); border: 1px solid var(--bg3); border-radius: 6px; padding: 8px 12px; font-size: 0.9rem; }
.form-input:focus { outline: none; border-color: var(--accent); }
.form-textarea { width: 100%; background: var(--bg3); color: var(--text); border: 1px solid var(--bg3); border-radius: 6px; padding: 8px 12px; font-size: 0.85rem; margin-top: 8px; resize: vertical; box-sizing: border-box; }
.form-textarea:focus { outline: none; border-color: var(--accent); }

.publish-form { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.checkbox-label { display: flex; align-items: center; gap: 4px; font-size: 0.85rem; color: var(--text2); cursor: pointer; }
.action-btns { display: flex; gap: 4px; }
.btn-xs { padding: 2px 8px; font-size: 0.8rem; border: 1px solid var(--bg3); border-radius: 4px; cursor: pointer; background: var(--bg2); color: var(--text); }
.btn-xs:hover { filter: brightness(1.2); }
.btn-sm { padding: 6px 14px; font-size: 0.85rem; border-radius: 6px; cursor: pointer; border: 1px solid transparent; }
.btn-accent { background: var(--accent); color: var(--bg); border: none; font-weight: 600; cursor: pointer; }
.btn-accent:hover { filter: brightness(1.2); }
.btn-green { border-color: var(--green); color: var(--green); }
.btn-amber { border-color: var(--amber); color: var(--amber); }
.btn-blue { border-color: var(--accent); color: var(--accent); }
.btn-red { border-color: var(--red); color: var(--red); }
.reject-form { display: flex; gap: 4px; align-items: center; }
.desc { font-size: 0.8rem; color: var(--text2); }
.installed-badge { font-size: 0.8rem; color: var(--green); }
.stars { color: var(--amber); letter-spacing: 1px; }
.grid-2-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 768px) { .grid-2-col { grid-template-columns: 1fr; } }
.tag { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 0.75rem; }
.tag.info { background: var(--accent); color: var(--bg); }
.tag.personality { background: #6366f1; color: white; }
.tag.agent { background: #f59e0b; color: white; }
.tag.workflow { background: #10b981; color: white; }
</style>
