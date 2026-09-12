import { createPinia, setActivePinia } from 'pinia'
import { describe, it, expect, beforeEach } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { installGuards } from '../router/guards'

beforeEach(() => { setActivePinia(createPinia()); sessionStorage.clear() })
function router() {
  const r = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/login', component: {}, meta: { guest: true } },
    { path: '/opportunities', component: {}, meta: { authenticated: true } },
    { path: '/workspace', component: {}, meta: { authenticated: true } },
  ] }); installGuards(r); return r
}
describe('route protection', () => {
  it('redirects anonymous users to login preserving destination', async () => {
    const r = router(); await r.push('/opportunities')
    expect(r.currentRoute.value.path).toBe('/login'); expect(r.currentRoute.value.query.next).toBe('/opportunities')
  })
  it('redirects signed-in users away from login', async () => {
    const auth = useAuthStore(); auth.restored = true
    auth.user = { id: 1, username: 's', role: 'sales', email: '', first_name: '', last_name: '' }
    const r = router(); await r.push('/login'); expect(r.currentRoute.value.path).toBe('/workspace')
  })
})
