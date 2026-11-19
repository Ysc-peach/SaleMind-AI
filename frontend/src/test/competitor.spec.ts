import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import type { AxiosAdapter } from 'axios'
import CompetitorView from '../views/CompetitorView.vue'
import { http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import type { Role } from '../types/domain'

const competitor = {
  id: 3,
  name: '竞品甲',
  aliases: '甲云',
  is_active: true,
  created_by_name: '售前甲',
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
}

const proposed = {
  id: 5,
  competitor: 3,
  competitor_name: '竞品甲',
  dimension: 'deployment',
  statement: '支持容器化部署',
  source_url: 'https://example.com/deploy',
  published_on: '2026-06-01',
  captured_on: '2026-11-19',
  status: 'proposed',
  created_by_name: '售前甲',
  reviewed_by_name: '',
  reviewed_at: null,
  created_at: '2026-11-19T00:00:00Z',
  updated_at: '2026-11-19T00:00:00Z',
}

let posts: { url: string; body: Record<string, unknown> }[] = []
let gets: string[] = []
let negativeClaim = false

const adapter: AxiosAdapter = async config => {
  const url = config.url!.replace(/^\/api/, '')
  const method = config.method ?? 'get'
  if (method === 'post') {
    posts.push({ url, body: config.data ? JSON.parse(String(config.data)) : {} })
    if (url.endsWith('/statements/') && negativeClaim) {
      return Promise.reject({
        response: {
          status: 400,
          data: { code: 'competitor_negative_claim', message: 'negative' },
        },
      })
    }
    if (url.includes('/statements/')) {
      return { data: proposed, status: 201, statusText: 'Created', headers: {}, config }
    }
    if (url.includes('/approve/') || url.includes('/reject/')) {
      return {
        data: { ...proposed, status: 'approved', reviewed_by_name: '管理员' },
        status: 200, statusText: 'OK', headers: {}, config,
      }
    }
    return { data: competitor, status: 201, statusText: 'Created', headers: {}, config }
  }
  gets.push(url)
  if (url.includes('/statements/')) {
    return {
      data: { count: 1, next: null, previous: null, results: [proposed] },
      status: 200, statusText: 'OK', headers: {}, config,
    }
  }
  return {
    data: { count: 1, next: null, previous: null, results: [competitor] },
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

async function mountView() {
  const wrapper = mount(CompetitorView, {
    global: { plugins: [ElementPlus] },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  posts = []
  gets = []
  negativeClaim = false
  setActivePinia(createPinia())
  http.defaults.adapter = adapter
})

describe('competitor library', () => {
  it('lets presales register a competitor', async () => {
    signIn('presales')
    const wrapper = await mountView()

    await wrapper.get('[data-test="competitor-new"]').trigger('click')
    await wrapper.get('[data-test="competitor-name"]').setValue('竞品甲')
    await wrapper.get('[data-test="competitor-aliases"]').setValue('甲云')
    await wrapper.get('[data-test="competitor-save"]').trigger('click')
    await flushPromises()

    expect(posts).toHaveLength(1)
    expect(posts[0]).toEqual({
      url: '/competitors/',
      body: { name: '竞品甲', aliases: '甲云' },
    })
    expect(wrapper.text()).toContain('已新增竞品')
    wrapper.unmount()
  })

  it('offers no write controls to a seller', async () => {
    signIn('sales')
    const wrapper = await mountView()

    expect(wrapper.find('[data-test="competitor-new"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="competitor-toggle-3"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('竞品甲')
    wrapper.unmount()
  })

  it('loads the statements of the selected competitor', async () => {
    signIn('presales')
    const wrapper = await mountView()

    await wrapper.get('[data-test="competitor-open-3"]').trigger('click')
    await flushPromises()

    expect(gets.at(-1)).toBe('/competitors/3/statements/')
    expect(wrapper.get('[data-test="statement-panel"]').text()).toContain(
      '支持容器化部署',
    )
    expect(wrapper.get('[data-test="statement-panel"]').text()).toContain('待审批')
    wrapper.unmount()
  })

  it('registers a statement with its dimension and source', async () => {
    signIn('presales')
    const wrapper = await mountView()
    await wrapper.get('[data-test="competitor-open-3"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-test="statement-new"]').trigger('click')
    await wrapper.get('[data-test="statement-dimension"]').setValue(
      'identity_integration',
    )
    await wrapper.get('[data-test="statement-text"]').setValue('支持 SAML 单点登录')
    await wrapper.get('[data-test="statement-url"]').setValue(
      'https://example.com/sso',
    )
    await wrapper.get('[data-test="statement-save"]').trigger('click')
    await flushPromises()

    const created = posts.find(item => item.url.endsWith('/statements/'))!
    expect(created.body).toMatchObject({
      dimension: 'identity_integration',
      statement: '支持 SAML 单点登录',
      source_url: 'https://example.com/sso',
    })
    expect(wrapper.text()).toContain('等待管理员审批')
    wrapper.unmount()
  })

  it('explains why a negative claim was refused', async () => {
    negativeClaim = true
    signIn('presales')
    const wrapper = await mountView()
    await wrapper.get('[data-test="competitor-open-3"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-test="statement-new"]').trigger('click')
    await wrapper.get('[data-test="statement-text"]').setValue('不支持私有化部署')
    await wrapper.get('[data-test="statement-url"]').setValue(
      'https://example.com/x',
    )
    await wrapper.get('[data-test="statement-save"]').trigger('click')
    await flushPromises()

    // The message has to tell the person what to do instead, not just say "400".
    expect(wrapper.text()).toContain('否定断言')
    wrapper.unmount()
  })

  it('lets only an administrator approve', async () => {
    signIn('presales')
    const presales = await mountView()
    await presales.get('[data-test="competitor-open-3"]').trigger('click')
    await flushPromises()
    expect(presales.find('[data-test="statement-approve-5"]').exists()).toBe(false)
    presales.unmount()

    signIn('admin')
    const admin = await mountView()
    await admin.get('[data-test="competitor-open-3"]').trigger('click')
    await flushPromises()
    await admin.get('[data-test="statement-approve-5"]').trigger('click')
    await flushPromises()

    expect(posts.map(item => item.url)).toContain(
      '/competitor-statements/5/approve/',
    )
    expect(admin.text()).toContain('陈述已批准')
    admin.unmount()
  })
})
