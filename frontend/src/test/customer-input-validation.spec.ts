import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { searchCustomers } from '../api/customers'
import { http } from '../api/http'
import { safeError } from '../utils/errors'
import CustomerDirectoryView from '../views/CustomerDirectoryView.vue'

vi.mock('../api/http', () => ({ http: { get: vi.fn(), post: vi.fn() } }))

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(http.get).mockResolvedValue({ data: { count: 0, results: [] } })
})
afterEach(() => vi.restoreAllMocks())

describe('customer search input bounds', () => {
  it.each(['a', '客', '😀'])('rejects 201 %s characters before any HTTP request', async character => {
    await expect(searchCustomers(`  ${character.repeat(201)}  `)).rejects.toMatchObject({
      code: 'customer_search_query_too_long',
    })
    expect(http.get).not.toHaveBeenCalled()
  })

  it.each(['a', '客', '😀'])('allows exactly 200 %s code points without truncating', async character => {
    const exact = character.repeat(200)
    await searchCustomers(`  ${exact}  `, 2)
    expect(http.get).toHaveBeenCalledWith('/customers/search/', { params: { q: exact, page: 2 } })
  })

  it('shows the same safe limit message for server and local validation', () => {
    const remote = { response: { status: 400, data: {
      code: 'customer_search_query_too_long', q: 'private customer query',
    } } }
    const local = Object.assign(new Error('private query and secret'), { code: 'customer_search_query_too_long' })
    for (const error of [remote, local]) {
      expect(safeError(error)).toContain('200')
      expect(safeError(error)).toContain('缩短')
      expect(safeError(error)).not.toContain('private')
      expect(safeError(error)).not.toContain('secret')
    }
  })

  it('keeps the complete invalid input visible and asks for correction, not empty results', async () => {
    const wrapper = mount(CustomerDirectoryView, { global: { stubs: {
      'el-button': { template: '<button @click="$emit(\'click\')"><slot /></button>' },
    } } })
    const query = '客'.repeat(201)
    const input = wrapper.get('input[placeholder="输入客户名称"]')
    await input.setValue(query)
    await input.trigger('keyup.enter')
    await flushPromises()

    expect(wrapper.text()).toContain('200')
    expect(wrapper.text()).not.toContain('未找到匹配客户')
    expect((input.element as HTMLInputElement).value).toBe(query)
    expect(http.get).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})

describe('safe budget validation messages', () => {
  it('explains a budget field error without displaying backend values', () => {
    const message = safeError({ response: { status: 400, data: {
      budget: ['private budget detail'], detail: 'secret value',
    } } })
    expect(message).toContain('预算')
    expect(message).toContain('0')
    expect(message).toContain('留空')
    expect(message).not.toContain('private')
    expect(message).not.toContain('secret')
  })

  it('does not turn a permission rejection into a budget validation error', () => {
    expect(safeError({ response: { status: 403, data: { budget: ['private'] } } })).toContain('权限')
  })
})
