import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import { http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import type { Opportunity, PresalesOption, Role } from '../types/domain'
import Workspace from '../views/OpportunityWorkspaceView.vue'

const original: Opportunity = {
  id: 7, project_name: '资料检索平台', customer: 3, customer_name: '客户公司',
  sales_owner: 1, sales_owner_name: '负责销售', presales_owner: null,
  presales_owner_name: '', raw_requirement: '需要私有化部署', stage: 'solution',
  status: 'active', budget: null, expected_launch_date: null, updated_at: '2026-10-12T00:00:00Z',
}
const people: PresalesOption[] = [
  { id: 2, username: 'pre', first_name: '小李', last_name: '售前' },
  { id: 3, username: 'pre2', first_name: '', last_name: '' },
]
let record: Opportunity
let options: PresalesOption[]
let calls: { method: string; url: string; data: unknown }[]
let optionsError: number | undefined
let patchError: number | undefined
let refreshError: boolean
let pausePatch: (() => Promise<void>) | undefined
let wrapper: VueWrapper | undefined

beforeEach(() => {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.restored = true
  auth.user = { id: 1, username: 'sales', role: 'sales', first_name: '', last_name: '', email: '' }
  record = { ...original }; options = [...people]; calls = []
  optionsError = undefined; patchError = undefined; refreshError = false; pausePatch = undefined
  http.defaults.adapter = async config => {
    const data = config.data ? JSON.parse(config.data) : undefined
    calls.push({ method: config.method!, url: config.url!, data })
    const response = (body: unknown) => ({ config, data: body, status: 200, statusText: 'OK', headers: {} })
    const reject = (status: number) => { throw { response: { status, data: { detail: 'secret provider traceback' } } } }
    if (config.url === '/users/presales-options/') {
      if (optionsError) reject(optionsError)
      return response(options)
    }
    if (config.method === 'patch') {
      if (pausePatch) await pausePatch()
      if (patchError) reject(patchError)
      record = { ...record, presales_owner: data.presales_owner, presales_owner_name: data.presales_owner === 2 ? '售前小李' : data.presales_owner === 3 ? 'pre2' : '' }
      // The real update serializer omits id and display names: refresh via GET.
      return response({ project_name: record.project_name, presales_owner: record.presales_owner, raw_requirement: record.raw_requirement, budget: null, stage: 'solution', status: 'active', expected_launch_date: null })
    }
    if (config.url === '/opportunities/8/') return response({ ...original, id: 8, project_name: '另一个商机' })
    if (refreshError && calls.some(c => c.method === 'patch')) reject(500)
    return response(record)
  }
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

async function openWorkspace(path = '/opportunities/7?tab=overview') {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/opportunities/:id', component: Workspace },
    { path: '/opportunities', component: { template: '<div>商机列表</div>' } },
  ] })
  await router.push(path)
  wrapper = mount({ template: '<RouterView />' }, { attachTo: document.body, global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return router
}
function button(text: string) {
  const found = wrapper!.findAll('button').find(b => b.text() === text)
  expect(found, `missing button: ${text}`).toBeDefined()
  return found!
}
async function openEditor() {
  await button(record.presales_owner === null ? '指派售前' : '更换售前').trigger('click')
  await flushPromises()
}
const patches = () => calls.filter(c => c.method === 'patch')

describe('existing opportunity Presales assignment', () => {
  it('assigns through a narrow PATCH and displays the refreshed server owner', async () => {
    await openWorkspace()
    expect(calls.map(c => c.url)).toEqual(['/opportunities/7/'])
    await openEditor()
    expect(wrapper!.get('select').findAll('option').map(o => o.text())).toContain('售前小李（pre）')
    await wrapper!.get('select').setValue('2')
    await button('保存售前指派').trigger('click'); await flushPromises()
    expect(patches()).toEqual([{ method: 'patch', url: '/opportunities/7/', data: { presales_owner: 2 } }])
    expect(wrapper!.get('.facts').text()).toContain('售前小李')
    expect(wrapper!.text()).toContain('售前指派已保存')
    expect(wrapper!.find('select').exists()).toBe(false)
  })

  it('replaces an existing owner and can explicitly clear the assignment', async () => {
    record = { ...record, presales_owner: 2, presales_owner_name: '售前小李' }
    await openWorkspace(); await openEditor()
    expect(wrapper!.get('select').element.value).toBe('2')
    await wrapper!.get('select').setValue('3')
    await button('保存售前指派').trigger('click'); await flushPromises()
    expect(wrapper!.get('.facts').text()).toContain('pre2')
    await openEditor(); await wrapper!.get('select').setValue('')
    await button('保存售前指派').trigger('click'); await flushPromises()
    expect(patches().map(p => p.data)).toEqual([{ presales_owner: 3 }, { presales_owner: null }])
    expect(wrapper!.get('.facts').text()).toContain('未指派')
  })

  it.each<[Role, number]>([['presales', 2], ['admin', 9], ['sales', 9]])('does not offer assignment to %s user %s', async (role, id) => {
    useAuthStore().user = { ...useAuthStore().user!, role, id }
    await openWorkspace()
    expect(wrapper!.text()).not.toContain('指派售前')
    expect(wrapper!.text()).not.toContain('更换售前')
    expect(calls.map(c => c.url)).toEqual(['/opportunities/7/'])
  })

  it('does not save unchanged selections and cancel discards local changes', async () => {
    await openWorkspace(); await openEditor()
    expect(button('保存售前指派').attributes('disabled')).toBeDefined()
    await wrapper!.get('select').setValue('2'); await button('取消').trigger('click')
    expect(patches()).toEqual([])
    expect(wrapper!.get('.facts').text()).toContain('未指派')
    await openEditor()
    expect(wrapper!.get('select').element.value).toBe('')
  })

  it('handles an empty candidate list without silently clearing an unavailable current owner', async () => {
    record = { ...record, presales_owner: 2, presales_owner_name: '售前小李' }; options = []
    await openWorkspace(); await openEditor()
    expect(wrapper!.text()).toContain('暂无可指派的在职售前')
    expect(wrapper!.get('select').element.value).toBe('2')
    expect(button('保存售前指派').attributes('disabled')).toBeDefined()
    expect(patches()).toEqual([])
  })

  it('blocks saving when candidate loading fails and offers a read-only retry', async () => {
    optionsError = 503
    await openWorkspace(); await openEditor()
    expect(wrapper!.get('[role="alert"]').text()).not.toContain('secret')
    expect(button('保存售前指派').attributes('disabled')).toBeDefined()
    optionsError = undefined
    await button('重新加载售前列表').trigger('click'); await flushPromises()
    await wrapper!.get('select').setValue('2')
    expect(button('保存售前指派').attributes('disabled')).toBeUndefined()
    expect(patches()).toEqual([])
  })

  it.each([400, 403, 500])('preserves the current owner and reports a safe PATCH %s rejection', async status => {
    patchError = status
    await openWorkspace(); await openEditor(); await wrapper!.get('select').setValue('2')
    await button('保存售前指派').trigger('click'); await flushPromises()
    expect(wrapper!.get('.facts').text()).toContain('未指派')
    expect(wrapper!.get('[role="alert"]').text()).not.toContain('secret')
    expect(wrapper!.text()).not.toContain('售前指派已保存')
    expect(patches()).toHaveLength(1)
  })

  it('distinguishes a successful PATCH followed by a failed detail refresh', async () => {
    refreshError = true
    await openWorkspace(); await openEditor(); await wrapper!.get('select').setValue('2')
    await button('保存售前指派').trigger('click'); await flushPromises()
    expect(record.presales_owner).toBe(2)
    expect(wrapper!.get('[role="alert"]').text()).toContain('指派已保存，但未能刷新')
    expect(wrapper!.text()).not.toContain('售前指派已保存。')
    expect(patches()).toHaveLength(1)
    expect(button('指派售前').attributes('disabled')).toBeDefined()
    refreshError = false
    await button('刷新售前负责人').trigger('click'); await flushPromises()
    expect(wrapper!.get('.facts').text()).toContain('售前小李')
    expect(wrapper!.find('[role="alert"]').exists()).toBe(false)
    expect(patches()).toHaveLength(1)
  })

  it('keeps a pending assignment in sync when moving between tabs of the same opportunity', async () => {
    let release!: () => void
    const pending = new Promise<void>(resolve => { release = resolve })
    pausePatch = () => pending
    const router = await openWorkspace(); await openEditor(); await wrapper!.get('select').setValue('2')
    await button('保存售前指派').trigger('click'); await flushPromises()
    await router.replace('/opportunities/7?tab=requirement'); await flushPromises()
    release(); await flushPromises()
    await router.replace('/opportunities/7?tab=overview'); await flushPromises()
    expect(wrapper!.get('.facts').text()).toContain('售前小李')
    expect(patches()).toHaveLength(1)
  })

  it('does not overwrite unsaved customer requirements when assigning Presales', async () => {
    const router = await openWorkspace('/opportunities/7?tab=requirement')
    await wrapper!.get('textarea').setValue('客户补充的未保存事实')
    await router.replace('/opportunities/7?tab=overview'); await flushPromises()
    await openEditor(); await wrapper!.get('select').setValue('2')
    await button('保存售前指派').trigger('click'); await flushPromises()
    await router.replace('/opportunities/7?tab=requirement'); await flushPromises()
    expect(wrapper!.get('textarea').element.value).toBe('客户补充的未保存事实')
    expect(button('保存客户需求').attributes('disabled')).toBeUndefined()
    expect(patches()[0]!.data).toEqual({ presales_owner: 2 })
  })

  it('prevents duplicate saves while the assignment request is in flight', async () => {
    let release!: () => void
    const pending = new Promise<void>(resolve => { release = resolve })
    pausePatch = () => pending
    await openWorkspace(); await openEditor(); await wrapper!.get('select').setValue('2')
    await button('保存售前指派').trigger('click'); await flushPromises()
    expect(button('保存售前指派').attributes('disabled')).toBeDefined()
    await button('保存售前指派').trigger('click'); await flushPromises()
    expect(patches()).toHaveLength(1)
    release(); await flushPromises()
    expect(wrapper!.get('.facts').text()).toContain('售前小李')
  })

  it('does not apply a late assignment result to another opportunity', async () => {
    let release!: () => void
    const pending = new Promise<void>(resolve => { release = resolve })
    pausePatch = () => pending
    const router = await openWorkspace(); await openEditor(); await wrapper!.get('select').setValue('2')
    await button('保存售前指派').trigger('click'); await flushPromises()
    await router.push('/opportunities/8?tab=overview'); await flushPromises()
    release(); await flushPromises()
    expect(wrapper!.text()).toContain('另一个商机')
    expect(wrapper!.get('.facts').text()).toContain('未指派')
    expect(wrapper!.text()).not.toContain('售前指派已保存')
  })
})
