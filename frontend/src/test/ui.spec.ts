import { beforeEach, describe, expect, it } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import { http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import OpportunityList from '../views/OpportunityListView.vue'
import Workspace from '../views/OpportunityWorkspaceView.vue'
import { safeError } from '../utils/errors'

export const opportunity = { id: 7, project_name: '合成售前项目', customer: 3, sales_owner: 1, presales_owner: 2, raw_requirement: '需要私有化部署', stage: 'solution', status: 'active', budget: '100000.00', expected_launch_date: null, updated_at: '2026-09-08T00:00:00Z' }
export function page<T>(results: T[]) { return { results, count: results.length, next: null, previous: null } }
beforeEach(() => {
  setActivePinia(createPinia()); const auth = useAuthStore(); auth.restored = true
  auth.user = { id: 1, username: 'sales', role: 'sales', first_name: '', last_name: '', email: '' }
  http.defaults.adapter = async config => ({ config, data: config.url === '/opportunities/' ? page([opportunity]) : opportunity, status: 200, statusText: 'OK', headers: {} })
})
async function mountAt(component: Parameters<typeof mount>[0], path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/opportunities', component: OpportunityList }, { path: '/opportunities/:id', component: Workspace }] })
  await router.push(path)
  const wrapper = mount(component, { global: { plugins: [router, ElementPlus] } }); await flushPromises(); return wrapper
}
describe('Opportunity UI', () => {
  it('shows API fields and links to the workspace', async () => {
    const w = await mountAt(OpportunityList, '/opportunities')
    expect(w.text()).toContain('合成售前项目'); expect(w.text()).toContain('方案制定')
    expect(w.find('a[href="/opportunities/7"]').exists()).toBe(true)
    w.unmount()
  })
  it('loads workspace and keeps requirements in the customer tab', async () => {
    const w = await mountAt(Workspace, '/opportunities/7?tab=requirement')
    expect(w.text()).toContain('合成售前项目'); expect(w.find('textarea').element.value).toBe('需要私有化部署')
    w.unmount()
  })
  it('does not offer customer fact editing to Presales', async () => {
    useAuthStore().user!.role = 'presales'; useAuthStore().user!.id = 2
    const w = await mountAt(Workspace, '/opportunities/7?tab=requirement')
    expect(w.find('textarea').exists()).toBe(false); expect(w.text()).toContain('需要私有化部署'); w.unmount()
  })
})
describe('safe failures', () => {
  it.each([401,403,404,409,422,500,502])('handles %s without rendering raw server content', status => {
    const message = safeError({ response: { status, data: { message: 'secret traceback', detail: 'raw provider' } } })
    expect(message).not.toContain('secret'); expect(message).not.toContain('raw provider'); expect(message.length).toBeGreaterThan(5)
  })
})
