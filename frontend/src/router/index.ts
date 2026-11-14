import { createRouter, createWebHistory } from 'vue-router'
import { installGuards } from './guards'
import AppShell from '../layouts/AppShell.vue'
export const router = createRouter({ history: createWebHistory(), routes: [
  { path: '/login', component: () => import('../views/LoginView.vue'), meta: { guest: true } },
  { path: '/', component: AppShell, meta: { authenticated: true }, children: [
    { path: '', redirect: '/workspace' },
    { path: 'workspace', component: () => import('../views/RoleWorkspaceView.vue') },
    { path: 'reviews', component: () => import('../views/PresalesWorkspaceView.vue') },
    { path: 'customers', component: () => import('../views/CustomerDirectoryView.vue') },
    { path: 'opportunities', component: () => import('../views/OpportunityListView.vue') },
    { path: 'audit', component: () => import('../views/AuditView.vue') },
    { path: 'opportunities/:id(\\d+)', component: () => import('../views/OpportunityWorkspaceView.vue') },
    { path: 'solutions/:id(\\d+)', component: () => import('../views/SolutionDetailView.vue') },
  ] },
  { path: '/:pathMatch(.*)*', redirect: '/workspace' },
] })
installGuards(router)
window.addEventListener('salesmind:expired', () => { if(router.currentRoute.value.path !== '/login') router.replace({path:'/login', query:{next:router.currentRoute.value.fullPath}}) })
