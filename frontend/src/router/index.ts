import { createRouter, createWebHistory } from 'vue-router'
import { installGuards } from './guards'
import AppShell from '../layouts/AppShell.vue'
export const router = createRouter({ history: createWebHistory(), routes: [
  { path: '/login', component: () => import('../views/LoginView.vue'), meta: { guest: true } },
  { path: '/', component: AppShell, meta: { authenticated: true }, children: [
    { path: '', redirect: '/opportunities' },
    { path: 'opportunities', component: () => import('../views/OpportunityListView.vue') },
    { path: 'opportunities/:id(\\d+)', component: () => import('../views/OpportunityWorkspaceView.vue') },
  ] },
  { path: '/:pathMatch(.*)*', redirect: '/opportunities' },
] })
installGuards(router)
window.addEventListener('salesmind:expired', () => { if(router.currentRoute.value.path !== '/login') router.replace({path:'/login', query:{next:router.currentRoute.value.fullPath}}) })
