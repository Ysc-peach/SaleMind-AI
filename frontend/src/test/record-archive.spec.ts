import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import type { AxiosAdapter } from 'axios'
import CustomerDirectoryView from '../views/CustomerDirectoryView.vue'
import OpportunityListView from '../views/OpportunityListView.vue'
import { http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import type { Role } from '../types/domain'

const customer = {
  id: 7,
  name: 'Acme',
  industry: 'Manufacturing',
  company_size: '200-500',
  basic_info: '',
  is_active: true,
  opportunities: [],
}

const opportunity = {
  id: 9,
  project_name: 'Rollout',
  customer: 7,
  customer_name: 'Acme',
  sales_owner: 1,
  sales_owner_name: '销售甲',
  presales_owner: null,
  stage: 'initial_contact',
  status: 'active',
  budget: null,
  expected_launch_date: null,
  is_active: true,
  updated_at: '2026-11-17T00:00:00Z',
}

let posts: string[] = []
let gets: { url: string; params: Record<string, unknown> }[] = []

const adapter: AxiosAdapter = async config => {
  const url = config.url!.replace(/^\/api/, '')
  if ((config.method ?? 'get') === 'post') {
    posts.push(url)
    return { data: {}, status: 200, statusText: 'OK', headers: {}, config }
  }
  gets.push({ url, params: { ...(config.params ?? {}) } })
  const page = { count: 1, next: null, previous: null, results: [customer] }
  return {
    data: url.startsWith('/opportunities')
      ? { ...page, results: [opportunity] }
      : page,
    status: 200, statusText: 'OK', headers: {}, config,
  }
}

function signIn(role: Role) {
  const auth = useAuthStore()
  auth.restored = true
  auth.user = {
    id: 1, username: 'someone', role, first_name: '', last_name: '', email: '',
  }
}

const stubs = { RouterLink: { template: '<a><slot /></a>' } }

beforeEach(() => {
  posts = []
  gets = []
  setActivePinia(createPinia())
  http.defaults.adapter = adapter
})

async function mountCustomers() {
  const wrapper = mount(CustomerDirectoryView, {
    global: { plugins: [ElementPlus], stubs },
  })
  await wrapper.get('input[placeholder="输入客户名称"]').setValue('Acme')
  await wrapper.get('.panel .row button').trigger('click')
  await flushPromises()
  return wrapper
}

describe('archiving records from the UI', () => {
  it('offers an administrator the archive action and reports the result', async () => {
    signIn('admin')
    const wrapper = await mountCustomers()

    await wrapper.get('[data-test="toggle-7"]').trigger('click')
    await flushPromises()

    expect(posts).toEqual(['/customers/7/disable/'])
    expect(wrapper.text()).toContain('客户已停用')
    wrapper.unmount()
  })

  it('does not offer the archive action to a seller', async () => {
    signIn('sales')
    const wrapper = await mountCustomers()

    expect(wrapper.find('[data-test="toggle-7"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('asks the server for archived rows only when the administrator opts in', async () => {
    signIn('admin')
    const wrapper = await mountCustomers()
    expect(gets[0].params.include_inactive).toBeUndefined()

    // el-checkbox keeps the input inside its label; clicking the root does not
    // toggle it, so drive the input directly.
    await wrapper.get('[data-test="show-inactive"] input').setValue(true)
    await flushPromises()

    expect(gets.at(-1)!.params.include_inactive).toBe('1')
    wrapper.unmount()
  })

  it('archives an opportunity from its list', async () => {
    signIn('admin')
    const wrapper = mount(OpportunityListView, {
      global: { plugins: [ElementPlus], stubs },
    })
    await flushPromises()

    await wrapper.get('[data-test="toggle-9"]').trigger('click')
    await flushPromises()

    expect(posts).toEqual(['/opportunities/9/disable/'])
    expect(wrapper.text()).toContain('商机已停用')
    wrapper.unmount()
  })
})
