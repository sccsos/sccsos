/**
 * SCCS OS API Client
 */
const API_BASE = '/api/v1';

export async function fetchJSON(url, options = {}) {
  const fullUrl = url.startsWith('/') ? `${API_BASE}${url}` : url;
  const res = await fetch(fullUrl, {
    headers: { 'Accept': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${err}`);
  }
  return res.json();
}

export const api = {
  // Generic GET (takes absolute or relative path)
  async get(path) {
    return fetchJSON(path);
  },

  // Health
  health: () => fetchJSON('/health'),

  // Agents
  agents: () => fetchJSON('/agents'),
  agentAction: (name, action) => fetchJSON(`/agents/${name}/${action}`, { method: 'POST' }),

  // Quota
  quota: (tenant = 'default') => fetchJSON(`/quotas/${tenant}`),
  quotaUpdate: (tenant, data) => fetchJSON(`/quotas/${tenant}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  }),

  // Billing
  billingSummary: (start, end, tenant) => {
    const params = new URLSearchParams({ start, end });
    if (tenant) params.set('tenant', tenant);
    return fetchJSON(`/billing/summary?${params}`);
  },
  billingExport: (start, end, tenant) => {
    const params = new URLSearchParams({ start, end });
    if (tenant) params.set('tenant', tenant);
    return `${API_BASE}/billing/export?${params}`;
  },

  // Traces
  traces: (limit = 20) => fetchJSON(`/traces?limit=${limit}`),

  // Skills — Market
  skills: (params = {}) => {
    const qs = new URLSearchParams();
    if (params.status) qs.set('status', params.status);
    if (params.type) qs.set('type', params.type);
    if (params.tag) qs.set('tag', params.tag);
    if (params.q) qs.set('q', params.q);
    const query = qs.toString();
    return fetchJSON(`/skills${query ? '?' + query : ''}`);
  },
  skillPublish: (data) => {
    const qs = new URLSearchParams({ name: data.name, type: data.type || 'personality' });
    if (data.author) qs.set('author', data.author);
    if (data.content) qs.set('content', data.content);
    if (data.tags) qs.set('tags', data.tags);
    if (data.auto_approve) qs.set('auto_approve', 'true');
    return fetchJSON(`/skills?${qs}`, { method: 'POST' });
  },
  skillInstall: (name, targetDir = '.') => fetchJSON(`/skills/${encodeURIComponent(name)}/install?target_dir=${targetDir}`, { method: 'POST' }),
  skillRemove: (name) => fetchJSON(`/skills/installed/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  skillsInstalled: () => fetchJSON('/skills/installed'),
  skillSubmitReview: (name) => fetchJSON(`/skills/${encodeURIComponent(name)}/submit`, { method: 'POST' }),
  skillApprove: (name, reviewer = 'admin') => fetchJSON(`/skills/${encodeURIComponent(name)}/approve?reviewer=${reviewer}`, { method: 'POST' }),
  skillReject: (name, reason) => fetchJSON(`/skills/${encodeURIComponent(name)}/reject?reason=${encodeURIComponent(reason)}`, { method: 'POST' }),

  // Skill Ratings
  skillRate: (name, score, userId, comment = '', version = '1.0') => {
    const qs = new URLSearchParams({ score, user_id: userId, version });
    if (comment) qs.set('comment', comment);
    return fetchJSON(`/skills/${encodeURIComponent(name)}/rate?${qs}`, { method: 'POST' });
  },
  skillRating: (name, version = '1.0') =>
    fetchJSON(`/skills/${encodeURIComponent(name)}/rating?version=${version}`),
  skillUserRating: (name, userId, version = '1.0') =>
    fetchJSON(`/skills/${encodeURIComponent(name)}/user-rating?user_id=${encodeURIComponent(userId)}&version=${version}`),
  skillTopRated: (limit = 10) => fetchJSON(`/skills/ratings/top?limit=${limit}`),
  skillPopular: (limit = 10) => fetchJSON(`/skills/popular?limit=${limit}`),
  skillMostInstalled: (limit = 10) => fetchJSON(`/skills/most-installed?limit=${limit}`),
  skillCategories: () => fetchJSON('/skills/categories'),

  // Webhooks
  webhooks: () => fetchJSON('/webhooks'),
  webhookAdd: (data) => fetchJSON('/webhooks', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  }),
  webhookDelete: (url) => fetchJSON(`/webhooks?url=${encodeURIComponent(url)}`, { method: 'DELETE' }),

  // Audit
  audit: (limit = 50) => fetchJSON(`/audit?limit=${limit}`),

  // Billing Plans (Subscription tiers)
  billingPlans: () => fetchJSON('/billing/plans'),
  billingPlanGet: (tenant) => fetchJSON(`/billing/plans/${encodeURIComponent(tenant)}`),
  billingPlanSet: (data) => fetchJSON('/billing/plans', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  }),
  billingPlanReset: (tenant) => fetchJSON(`/billing/plans/${encodeURIComponent(tenant)}`, { method: 'DELETE' }),
};
