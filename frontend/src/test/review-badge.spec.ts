import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import ElementPlus from 'element-plus'
import axios, { type AxiosAdapter } from 'axios'
import AppShell from '../layouts/AppShell.vue'
import { useAuthStore } from '../stores/auth'
import { http } from '../api/http'

let calls: string[] = []
let total = 0

const adapter: AxiosAdapter = async config => {
  const url = config.url!.replace(/^\/api/, '')
  calls.push(url)
  const data = url === '/reviews/summary/'
    ? { pending_reviews: total, technical_revisions: 0, total }
    : {}
  return { data, status: 200, statusText: 'OK', headers: {}, config }
}

beforeEach(() => {
  calls = []
  total = 0
  axios.defaults.adapter = adapter
  http.defaults.adapter = adapter
})

async function mountShell(role: 'presales' | 'sales', token: string) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.restored = true
  auth.accessToken = token
  auth.user = { id: 2, username: role, role, email: '', first_name: '', last_name: '' }
  const placeholder = { template: '<div />' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/',
        component: AppShell,
        children: [
          { path: '', component: placeholder },
          { path: 'workspace', component: placeholder },
          { path: 'reviews', component: placeholder },
        ],
      },
      { path: '/opportunities', component: placeholder },
    ],
  })
  await router.push('/')
  await router.isReady()
  const wrapper = mount(RouterView, { global: { plugins: [pinia, router, ElementPlus] } })
  await flushPromises()
  return { wrapper, router }
}

describe('pending review badge', () => {
  it('shows the server count on the reviews entry for presales', async () => {
    total = 3
    const { wrapper } = await mountShell('presales', 'token')

    expect(wrapper.get('[data-test="review-badge"]').text()).toBe('3')
    expect(calls).toContain('/reviews/summary/')
    wrapper.unmount()
  })

  it('hides the badge when nothing is waiting', async () => {
    total = 0
    const { wrapper } = await mountShell('presales', 'token')

    expect(wrapper.find('[data-test="review-badge"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('does not ask for presales counts when the user is a seller', async () => {
    total = 5
    const { wrapper } = await mountShell('sales', 'token')

    expect(wrapper.find('[data-test="review-badge"]').exists()).toBe(false)
    expect(calls).not.toContain('/reviews/summary/')
    wrapper.unmount()
  })

  it('refreshes the count when the route changes', async () => {
    total = 2
    const { wrapper, router } = await mountShell('presales', 'token')
    expect(wrapper.get('[data-test="review-badge"]').text()).toBe('2')

    total = 1
    await router.push('/workspace')
    await flushPromises()

    expect(wrapper.get('[data-test="review-badge"]').text()).toBe('1')
    wrapper.unmount()
  })
})
