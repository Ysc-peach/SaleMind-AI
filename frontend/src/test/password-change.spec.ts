import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import ElementPlus from 'element-plus'
import axios, { AxiosError, type AxiosAdapter } from 'axios'
import AppShell from '../layouts/AppShell.vue'
import { useAuthStore } from '../stores/auth'
import { http } from '../api/http'

type Call = { url: string; body?: Record<string, unknown> }

let calls: Call[] = []
let rejectWith: Record<string, string[]> | null = null

const adapter: AxiosAdapter = async config => {
  const url = config.url!.replace(/^\/api/, '')
  calls.push({ url, body: config.data ? JSON.parse(String(config.data)) : undefined })
  if (rejectWith) {
    throw new AxiosError('redacted', 'ERR_BAD_REQUEST', config, null, {
      data: rejectWith, status: 400, statusText: '', headers: {}, config,
    })
  }
  return { data: {}, status: 200, statusText: 'OK', headers: {}, config }
}

beforeEach(() => {
  calls = []
  rejectWith = null
  sessionStorage.clear()
  axios.defaults.adapter = adapter
  http.defaults.adapter = adapter
})

async function mountShell() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.restored = true
  auth.user = { id: 1, username: 'sales', role: 'sales', email: '', first_name: '', last_name: '' }
  const placeholder = { template: '<div />' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: AppShell, children: [{ path: '', component: placeholder }] },
      { path: '/workspace', component: placeholder },
      { path: '/opportunities', component: placeholder },
      { path: '/login', component: placeholder },
    ],
  })
  await router.push('/')
  await router.isReady()
  const wrapper = mount(RouterView, { global: { plugins: [pinia, router, ElementPlus] } })
  return { wrapper, router }
}

async function fill(wrapper: Awaited<ReturnType<typeof mountShell>>['wrapper'], confirm?: string) {
  await wrapper.get('[data-test="open-password"]').trigger('click')
  await wrapper.get('[data-test="password-current"]').setValue('OldPassword123!')
  await wrapper.get('[data-test="password-next"]').setValue('NewPassword456!')
  await wrapper.get('[data-test="password-confirm"]').setValue(confirm ?? 'NewPassword456!')
}

describe('self-service password change', () => {
  it('rejects a mismatched confirmation without calling the API', async () => {
    const { wrapper } = await mountShell()
    await fill(wrapper, 'DifferentPassword789!')

    await wrapper.get('[data-test="password-form"]').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[data-test="password-error"]').text()).toContain('不一致')
    expect(calls).toHaveLength(0)
    wrapper.unmount()
  })

  it('posts the change and signs out because every session is revoked', async () => {
    const { wrapper, router } = await mountShell()
    sessionStorage.setItem('salesmind.refresh', 'test-refresh')
    await fill(wrapper)

    await wrapper.get('[data-test="password-form"]').trigger('submit')
    await flushPromises()

    expect(calls[0]).toEqual({
      url: '/auth/password/',
      body: { current_password: 'OldPassword123!', new_password: 'NewPassword456!' },
    })
    expect(calls.map(call => call.url)).toContain('/auth/logout/')
    expect(useAuthStore().user).toBeNull()
    expect(router.currentRoute.value.path).toBe('/login')
    wrapper.unmount()
  })

  it('shows the server field message when the current password is wrong', async () => {
    rejectWith = { current_password: ['The current password is incorrect.'] }
    const { wrapper } = await mountShell()
    await fill(wrapper)

    await wrapper.get('[data-test="password-form"]').trigger('submit')
    await flushPromises()

    expect(wrapper.get('[data-test="password-error"]').text()).toContain('incorrect')
    expect(useAuthStore().user?.username).toBe('sales')
    wrapper.unmount()
  })
})
