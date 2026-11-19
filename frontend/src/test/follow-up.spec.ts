import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import type { AxiosAdapter } from 'axios'
import FollowUpPanel from '../components/FollowUpPanel.vue'
import { http } from '../api/http'

const tasks = [
  {
    id: 1, opportunity: 7, title: '回访客户', due_on: '2026-01-05', owner: 3,
    owner_name: '销售甲', status: 'open', completed_at: null, is_overdue: true,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 2, opportunity: 7, title: '发送 POC 计划', due_on: '2099-01-05', owner: 3,
    owner_name: '销售甲', status: 'open', completed_at: null, is_overdue: false,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  },
]

let posts: { url: string; body: Record<string, unknown> }[] = []

const adapter: AxiosAdapter = async config => {
  const url = config.url!.replace(/^\/api/, '')
  const method = config.method ?? 'get'
  if (method === 'post') {
    posts.push({ url, body: config.data ? JSON.parse(String(config.data)) : {} })
    return { data: tasks[0], status: 200, statusText: 'OK', headers: {}, config }
  }
  return {
    data: { count: tasks.length, next: null, previous: null, results: tasks },
    status: 200, statusText: 'OK', headers: {}, config,
  }
}

async function mountPanel(readOnly = false) {
  const wrapper = mount(FollowUpPanel, {
    props: { opportunityId: 7, readOnly },
    global: { plugins: [ElementPlus] },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  posts = []
  http.defaults.adapter = adapter
})

describe('follow-up panel', () => {
  it('marks only the late task as overdue', async () => {
    const wrapper = await mountPanel()

    const items = wrapper.findAll('[data-test^="follow-up-"]')
    const late = wrapper.get('[data-test="follow-up-1"]')
    const later = wrapper.get('[data-test="follow-up-2"]')

    expect(late.text()).toContain('已逾期')
    expect(later.text()).not.toContain('已逾期')
    expect(items.length).toBeGreaterThanOrEqual(2)
    wrapper.unmount()
  })

  it('adds a task with the title and date the person typed', async () => {
    const wrapper = await mountPanel()

    await wrapper.get('[data-test="follow-up-title"]').setValue('  确认 POC 时间  ')
    await wrapper.get('[data-test="follow-up-due"]').setValue('2026-02-01')
    await wrapper.get('[data-test="follow-up-add"]').trigger('click')
    await flushPromises()

    expect(posts).toHaveLength(1)
    expect(posts[0].url).toBe('/opportunities/7/follow-ups/')
    expect(posts[0].body).toEqual({ title: '确认 POC 时间', due_on: '2026-02-01' })
    expect(wrapper.text()).toContain('已添加跟进事项')
    expect((wrapper.get('[data-test="follow-up-title"]').element as HTMLInputElement).value).toBe('')
    wrapper.unmount()
  })

  it('does not post an empty task', async () => {
    const wrapper = await mountPanel()

    await wrapper.get('[data-test="follow-up-title"]').setValue('   ')
    await wrapper.get('[data-test="follow-up-add"]').trigger('click')
    await flushPromises()

    expect(posts).toHaveLength(0)
    wrapper.unmount()
  })

  it('completes a task through the server action', async () => {
    const wrapper = await mountPanel()

    await wrapper.get('[data-test="follow-up-toggle-1"]').trigger('click')
    await flushPromises()

    expect(posts.map(item => item.url)).toEqual(['/follow-ups/1/complete/'])
    wrapper.unmount()
  })

  it('hides the write controls from someone who cannot manage them', async () => {
    const wrapper = await mountPanel(true)

    expect(wrapper.find('[data-test="follow-up-add"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="follow-up-toggle-1"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('回访客户')
    wrapper.unmount()
  })
})
