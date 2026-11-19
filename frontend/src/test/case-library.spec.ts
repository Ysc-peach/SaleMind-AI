import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import type { AxiosAdapter } from 'axios'
import CaseStudyView from '../views/CaseStudyView.vue'
import SimilarCasesPanel from '../components/SimilarCasesPanel.vue'
import { http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import type { Role } from '../types/domain'

const caseRow = {
  id: 3,
  title: '制造业知识库一期',
  industry: 'manufacturing',
  size_band: 'medium',
  customer_name: '某某集团',
  pain_points: '文档散落',
  approach: '分阶段迁移',
  results: '命中率提升',
  referenceable: true,
  is_active: true,
  created_by_name: '售前甲',
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
}

let posts: { url: string; body: Record<string, unknown> }[] = []
let gets: { url: string; params: Record<string, unknown> }[] = []

const adapter: AxiosAdapter = async config => {
  const url = config.url!.replace(/^\/api/, '')
  if ((config.method ?? 'get') === 'post') {
    posts.push({ url, body: config.data ? JSON.parse(String(config.data)) : {} })
    return { data: caseRow, status: 201, statusText: 'Created', headers: {}, config }
  }
  gets.push({ url, params: { ...(config.params ?? {}) } })
  return {
    data: { count: 1, next: null, previous: null, results: [caseRow] },
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

async function mountLibrary() {
  const wrapper = mount(CaseStudyView, {
    global: {
      plugins: [ElementPlus],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  posts = []
  gets = []
  setActivePinia(createPinia())
  http.defaults.adapter = adapter
})

describe('case library', () => {
  it('lets presales create a case and sends the typed values', async () => {
    signIn('presales')
    const wrapper = await mountLibrary()

    await wrapper.get('[data-test="case-new"]').trigger('click')
    await wrapper.get('[data-test="case-title"]').setValue('制造业知识库一期')
    await wrapper.get('[data-test="case-industry"]').setValue('manufacturing')
    await wrapper.get('[data-test="case-save"]').trigger('click')
    await flushPromises()

    expect(posts).toHaveLength(1)
    expect(posts[0].url).toBe('/case-studies/')
    expect(posts[0].body).toMatchObject({
      title: '制造业知识库一期',
      industry: 'manufacturing',
      size_band: 'medium',
    })
    expect(wrapper.text()).toContain('案例已创建')
    wrapper.unmount()
  })

  it('refuses to submit without a title', async () => {
    signIn('presales')
    const wrapper = await mountLibrary()

    await wrapper.get('[data-test="case-new"]').trigger('click')
    await wrapper.get('[data-test="case-save"]').trigger('click')
    await flushPromises()

    expect(posts).toHaveLength(0)
    expect(wrapper.text()).toContain('必填')
    wrapper.unmount()
  })

  it('offers no write controls to a seller', async () => {
    signIn('sales')
    const wrapper = await mountLibrary()

    expect(wrapper.find('[data-test="case-new"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="case-toggle-3"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('制造业知识库一期')
    wrapper.unmount()
  })

  it('archives a case through the server action', async () => {
    signIn('presales')
    const wrapper = await mountLibrary()

    await wrapper.get('[data-test="case-toggle-3"]').trigger('click')
    await flushPromises()

    expect(posts.map(item => item.url)).toEqual(['/case-studies/3/archive/'])
    wrapper.unmount()
  })

  it('shows the archived filter to an administrator only', async () => {
    signIn('admin')
    const admin = await mountLibrary()
    expect(admin.find('[data-test="case-filter-inactive"]').exists()).toBe(true)
    admin.unmount()

    signIn('presales')
    const presales = await mountLibrary()
    expect(presales.find('[data-test="case-filter-inactive"]').exists()).toBe(false)
    presales.unmount()
  })

  it('sends only the filters the operator set', async () => {
    signIn('presales')
    const wrapper = await mountLibrary()
    gets = []

    await wrapper.get('[data-test="case-filter-industry"]').setValue('manufacturing')
    await wrapper.get('[data-test="case-apply"]').trigger('click')
    await flushPromises()

    expect(gets.at(-1)!.params).toMatchObject({ industry: 'manufacturing', page: 1 })
    expect(gets.at(-1)!.params).not.toHaveProperty('q')
    wrapper.unmount()
  })
})

describe('similar cases panel', () => {
  it('ranks cases and hides the name of a non-referenceable one', async () => {
    const anonymous = { ...caseRow, id: 4, title: '金融案例', referenceable: false }
    http.defaults.adapter = async config => {
      gets.push({ url: config.url!.replace(/^\/api/, ''), params: {} })
      return {
        data: { results: [caseRow, anonymous] },
        status: 200, statusText: 'OK', headers: {}, config,
      }
    }
    const wrapper = mount(SimilarCasesPanel, {
      props: { industry: 'manufacturing' },
      global: {
        plugins: [ElementPlus],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    await flushPromises()

    expect(wrapper.get('[data-test="similar-cases"]').text()).toContain('制造业知识库一期')
    expect(wrapper.get('[data-test="similar-case-3"]').text()).toContain('某某集团')
    expect(wrapper.get('[data-test="similar-case-4"]').text()).toContain('匿名客户')
    wrapper.unmount()
  })
})
