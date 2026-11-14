import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import type { AxiosAdapter } from 'axios'
import AuditView from '../views/AuditView.vue'
import { http } from '../api/http'

let payload: Record<string, unknown> = {}

const adapter: AxiosAdapter = async config => ({
  data: payload, status: 200, statusText: 'OK', headers: {}, config,
})

beforeEach(() => {
  payload = { reviews: [], generations: [], limit: 50 }
  http.defaults.adapter = adapter
})

function mountView() {
  return mount(AuditView, {
    global: {
      plugins: [ElementPlus],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
}

describe('audit view', () => {
  it('renders review and generation history with readable statuses', async () => {
    payload = {
      limit: 50,
      reviews: [{
        id: 1,
        opportunity_id: 4,
        project_name: 'Audit project',
        submitted_by: 'Alice Chen',
        reviewer: 'Pat Lee',
        status: 'RETURNED',
        return_reason: 'technical_revision_required',
        submitted_at: '2026-11-14T02:00:00Z',
        decided_at: '2026-11-14T03:00:00Z',
      }],
      generations: [{
        id: 9,
        opportunity_id: 4,
        project_name: 'Audit project',
        requested_by: 'Alice Chen',
        status: 'FAILED',
        error_code: 'solution_draft_not_grounded',
        created_at: '2026-11-14T01:00:00Z',
        finished_at: '2026-11-14T01:02:00Z',
      }],
    }
    const wrapper = mountView()
    await flushPromises()

    const reviews = wrapper.get('[data-test="audit-reviews"]')
    expect(reviews.text()).toContain('Audit project')
    expect(reviews.text()).toContain('Alice Chen')
    expect(reviews.text()).toContain('Pat Lee')
    expect(reviews.text()).toContain('已退回')
    expect(reviews.text()).toContain('需要修改技术方案')

    const generations = wrapper.get('[data-test="audit-generations"]')
    expect(generations.text()).toContain('已失败')
    expect(generations.text()).toContain('solution_draft_not_grounded')
    wrapper.unmount()
  })

  it('explains an empty trail instead of rendering bare tables', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.get('[data-test="audit-reviews"]').text()).toContain('还没有审核记录')
    expect(wrapper.get('[data-test="audit-generations"]').text()).toContain('还没有生成任务')
    wrapper.unmount()
  })
})
