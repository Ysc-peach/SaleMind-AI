import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import type { AxiosAdapter } from 'axios'
import AuditView from '../views/AuditView.vue'
import { http } from '../api/http'

type Params = Record<string, string | number>

let payload: Record<string, unknown> = {}
let requests: Params[] = []

const adapter: AxiosAdapter = async config => {
  requests.push((config.params ?? {}) as Params)
  return { data: payload, status: 200, statusText: 'OK', headers: {}, config }
}

function page(count: number, results: unknown[]) {
  return { count, results }
}

function view() {
  return mount(AuditView, {
    global: {
      plugins: [ElementPlus],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
}

beforeEach(() => {
  requests = []
  payload = {
    page: 1,
    page_size: 20,
    filters: { actor: '', status: '', date_from: null, date_to: null },
    reviews: page(0, []),
    generations: page(0, []),
  }
  http.defaults.adapter = adapter
})

describe('audit view', () => {
  it('renders review and generation history with readable statuses', async () => {
    payload = {
      page: 1,
      page_size: 20,
      filters: { actor: '', status: '', date_from: null, date_to: null },
      reviews: page(1, [{
        id: 1,
        opportunity_id: 4,
        project_name: 'Audit project',
        submitted_by: 'Alice Chen',
        reviewer: 'Pat Lee',
        status: 'RETURNED',
        return_reason: 'technical_revision_required',
        submitted_at: '2026-11-14T02:00:00Z',
        decided_at: '2026-11-14T03:00:00Z',
      }]),
      generations: page(1, [{
        id: 9,
        opportunity_id: 4,
        project_name: 'Audit project',
        requested_by: 'Alice Chen',
        status: 'FAILED',
        error_code: 'solution_draft_not_grounded',
        created_at: '2026-11-14T01:00:00Z',
        finished_at: '2026-11-14T01:02:00Z',
      }]),
    }
    const wrapper = view()
    await flushPromises()

    const reviews = wrapper.get('[data-test="audit-reviews"]')
    expect(reviews.text()).toContain('Audit project')
    expect(reviews.text()).toContain('Alice Chen')
    expect(reviews.text()).toContain('Pat Lee')
    expect(reviews.text()).toContain('已退回')
    expect(reviews.text()).toContain('需要修改技术方案')
    expect(reviews.text()).toContain('共 1 条')

    const generations = wrapper.get('[data-test="audit-generations"]')
    expect(generations.text()).toContain('已失败')
    expect(generations.text()).toContain('solution_draft_not_grounded')
    wrapper.unmount()
  })

  it('explains an empty result instead of rendering bare tables', async () => {
    const wrapper = view()
    await flushPromises()

    expect(wrapper.get('[data-test="audit-reviews"]').text()).toContain('没有符合条件的审核记录')
    expect(wrapper.get('[data-test="audit-generations"]').text()).toContain('没有符合条件的生成任务')
    wrapper.unmount()
  })

  it('sends the chosen filters and returns to the first page', async () => {
    payload = {
      page: 1,
      page_size: 20,
      filters: { actor: '', status: '', date_from: null, date_to: null },
      reviews: page(45, []),
      generations: page(0, []),
    }
    const wrapper = view()
    await flushPromises()
    await wrapper.get('[data-test="audit-next"]').trigger('click')
    await flushPromises()
    expect(requests.at(-1)).toMatchObject({ page: 2 })

    await wrapper.get('[data-test="filter-actor"]').setValue('alice')
    await wrapper.get('[data-test="filter-status"]').setValue('RETURNED')
    await wrapper.get('[data-test="audit-search"]').trigger('click')
    await flushPromises()

    expect(requests.at(-1)).toMatchObject({
      page: 1,
      actor: 'alice',
      status: 'RETURNED',
    })
    wrapper.unmount()
  })

  it('only offers the next page while rows remain', async () => {
    payload = {
      page: 1,
      page_size: 20,
      filters: { actor: '', status: '', date_from: null, date_to: null },
      reviews: page(20, []),
      generations: page(3, []),
    }
    const wrapper = view()
    await flushPromises()

    // Exactly one page of reviews and fewer generations: nothing left to fetch.
    expect(wrapper.get('[data-test="audit-next"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-test="audit-prev"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
})
