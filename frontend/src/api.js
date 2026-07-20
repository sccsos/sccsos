/**
 * SCCS OS API Client
 */
const API_BASE = '/api/v1';

export async function fetchJSON(url, options = {}) {
  const res = await fetch(`${API_BASE}${url}`, {
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
  // Health
  health: () => fetchJSON('/health'),

  // Agents
  agents: () => fetchJSON('/agents'),
  agentAction: (name, action) => fetchJSON(`/agents/${name}/${action}`, { method: 'POST' }),

  // Quota
  quota: (tenant = 'default') => fetchJSON(`/quotas/${tenant}`),

  // Billing
  billingSummary: (start, end, tenant) => {
    const params = new URLSearchParams({ start, end });
    if (tenant) params.set('tenant', tenant);
    return fetchJSON(`/billing/summary?${params}`);
  },

  // Traces
  traces: (limit = 20) => fetchJSON(`/traces?limit=${limit}`),

  // Skills
  skills: (status = 'all') => fetchJSON(`/skills?status=${status}`),
  skillPublish: (data) => fetchJSON('/skills', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }),

  // Audit
  audit: (limit = 50) => fetchJSON(`/audit?limit=${limit}`),
};
