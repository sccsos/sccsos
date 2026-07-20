import { createRouter, createWebHistory } from 'vue-router';

const routes = [
  { path: '/', name: 'Dashboard', component: () => import('../views/Dashboard.vue') },
  { path: '/agents', name: 'Agents', component: () => import('../views/Agents.vue') },
  { path: '/quota', name: 'Quota', component: () => import('../views/Quota.vue') },
  { path: '/billing', name: 'Billing', component: () => import('../views/Billing.vue') },
  { path: '/skills', name: 'Skills', component: () => import('../views/Skills.vue') },
  { path: '/traces', name: 'Traces', component: () => import('../views/Traces.vue') },
  { path: '/webhooks', name: 'Webhooks', component: () => import('../views/Webhooks.vue') },
];

export default createRouter({
  history: createWebHistory(),
  routes,
});
