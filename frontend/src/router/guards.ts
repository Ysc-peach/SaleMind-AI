import type { Router } from 'vue-router'
import { useAuthStore } from '../stores/auth'

export function installGuards(router: Router) {
  router.beforeEach(async to => {
    const auth = useAuthStore(); await auth.restore()
    if (to.meta.authenticated && !auth.user) return { path: '/login', query: { next: to.fullPath } }
    if (to.meta.guest && auth.user) return '/workspace'
  })
}
