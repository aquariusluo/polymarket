import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/overview' },
    { path: '/overview', name: 'overview', component: () => import('../views/OverviewView.vue') },
    { path: '/portfolio', name: 'portfolio', component: () => import('../views/PortfolioView.vue') },
    { path: '/signals', name: 'signals', component: () => import('../views/SignalsView.vue') },
    { path: '/leaders', name: 'leaders', component: () => import('../views/LeadersView.vue') },
    { path: '/pipeline', name: 'pipeline', component: () => import('../views/PipelineView.vue') },
  ],
})

export default router
