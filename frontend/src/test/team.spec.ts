import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import type { AxiosAdapter } from 'axios'
import TeamView from '../views/TeamView.vue'
import { http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import type { Role } from '../types/domain'

const boss = {
  id: 1,
  username: 'boss',
  email: 'boss@example.com',
  first_name: '老',
  last_name: '板',
  role: 'admin',
  role_label: '管理员',
  is_active: true,
  date_joined: '2026-01-01T00:00:00Z',
  last_login: '2026-11-21T00:00:00Z',
}

const seller = {
  id: 2,
  username: 'seller',
  email: 'seller@example.com',
  first_name: '张',
  last_name: '三',
  role: 'sales',
  role_label: '销售',
  is_active: true,
  date_joined: '2026-02-01T00:00:00Z',
  last_login: null,
}

let posts: { url: string; body: Record<string, unknown> }[] = []
let patches: { url: string; body: Record<string, unknown> }[] = []
let refuseWith: { status: number; code: string } | null = null

const adapter: AxiosAdapter = async config => {
  const url = config.url!.replace(/^\/api/, '')
  const method = config.method ?? 'get'
  if (method !== 'get') {
    const body = config.data ? JSON.parse(String(config.data)) : {}
    if (refuseWith) {
      const response = refuseWith
      refuseWith = null
      return Promise.reject({ response: { status: response.status, data: { code: response.code } } })
    }
    if (method === 'patch') {
      patches.push({ url, body })
      return { data: seller, status: 200, statusText: 'OK', headers: {}, config }
    }
    posts.push({ url, body })
    return { data: seller, status: 201, statusText: 'Created', headers: {}, config }
  }
  return {
    data: { count: 2, next: null, previous: null, results: [boss, seller] },
    status: 200, statusText: 'OK', headers: {}, config,
  }
}

function signIn(role: Role) {
  const auth = useAuthStore()
  auth.restored = true
  auth.user = { id: 1, username: 'boss', role, first_name: '', last_name: '', email: '' }
}

async function mountView() {
  const wrapper = mount(TeamView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  posts = []
  patches = []
  refuseWith = null
  setActivePinia(createPinia())
  http.defaults.adapter = adapter
})

describe('team page', () => {
  it('lists the accounts without any credential fields', async () => {
    signIn('admin')
    const wrapper = await mountView()

    const row = wrapper.get('[data-test="team-row-2"]').text()
    expect(row).toContain('seller')
    expect(row).toContain('张 三')
    expect(wrapper.text()).not.toContain('password')
    wrapper.unmount()
  })

  it('creates an account with the typed values', async () => {
    signIn('admin')
    const wrapper = await mountView()

    await wrapper.get('[data-test="team-new"]').trigger('click')
    await wrapper.get('[data-test="team-username"]').setValue('newbie')
    await wrapper.get('[data-test="team-email"]').setValue('newbie@example.com')
    await wrapper.get('[data-test="team-role"]').setValue('presales')
    await wrapper.get('[data-test="team-password"]').setValue('StrongPassword123!')
    await wrapper.get('[data-test="team-save"]').trigger('click')
    await flushPromises()

    expect(posts[0]).toEqual({
      url: '/users/',
      body: {
        username: 'newbie',
        email: 'newbie@example.com',
        role: 'presales',
        password: 'StrongPassword123!',
        first_name: '',
        last_name: '',
      },
    })
    expect(wrapper.text()).toContain('已创建账号')
    wrapper.unmount()
  })

  it('refuses to submit an incomplete form', async () => {
    signIn('admin')
    const wrapper = await mountView()

    await wrapper.get('[data-test="team-new"]').trigger('click')
    await wrapper.get('[data-test="team-save"]').trigger('click')
    await flushPromises()

    expect(posts).toHaveLength(0)
    expect(wrapper.text()).toContain('都必须填写')
    wrapper.unmount()
  })

  it('changes a role and says the sessions died with it', async () => {
    signIn('admin')
    const wrapper = await mountView()

    await wrapper.get('[data-test="team-role-2"]').setValue('presales')
    await flushPromises()

    expect(patches[0]).toEqual({ url: '/users/2/', body: { role: 'presales' } })
    expect(wrapper.text()).toContain('现有会话已失效')
    wrapper.unmount()
  })

  it('explains why the last administrator cannot be demoted', async () => {
    signIn('admin')
    const wrapper = await mountView()
    refuseWith = { status: 409, code: 'user_last_admin' }

    await wrapper.get('[data-test="team-role-2"]').setValue('sales')
    await flushPromises()

    expect(wrapper.text()).toContain('最后一名有效管理员')
    wrapper.unmount()
  })

  it('deactivates and resets a password through the server actions', async () => {
    signIn('admin')
    const wrapper = await mountView()

    await wrapper.get('[data-test="team-toggle-2"]').trigger('click')
    await flushPromises()
    expect(posts[0].url).toBe('/users/2/deactivate/')

    await wrapper.get('[data-test="team-reset-2"]').trigger('click')
    await wrapper.get('[data-test="team-new-password"]').setValue('AnotherStrongPass456!')
    await wrapper.get('[data-test="team-reset-save"]').trigger('click')
    await flushPromises()

    expect(posts[1]).toEqual({
      url: '/users/2/password/',
      body: { password: 'AnotherStrongPass456!' },
    })
    wrapper.unmount()
  })

  it('offers no write controls to a non-administrator', async () => {
    signIn('presales')
    const wrapper = await mountView()

    expect(wrapper.find('[data-test="team-new"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="team-role-2"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="team-toggle-2"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('seller')
    wrapper.unmount()
  })
})
