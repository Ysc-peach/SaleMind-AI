import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import type { AxiosAdapter } from 'axios'
import QuotePanel from '../components/QuotePanel.vue'
import { http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import type { Role } from '../types/domain'

const entry = {
  id: 11,
  sku: 'SKU-1',
  name: '标准版',
  category: '软件',
  unit: '套',
  unit_price: '1000.00',
  currency: 'CNY',
  effective_from: '2026-01-01',
  is_active: true,
}

const line = {
  id: 21,
  sku: 'SKU-1',
  name: '标准版',
  unit: '套',
  quantity: '2.00',
  unit_price: '1000.00',
  currency: 'CNY',
  subtotal: '2000.00',
  removed_at: null,
  created_at: '2026-11-21T00:00:00Z',
}

function makeQuote(overrides: Record<string, unknown> = {}) {
  return {
    id: 31,
    opportunity: 7,
    solution_draft: 5,
    discount_percent: '0.00',
    discount_approval: {
      threshold_percent: '15.00',
      required: false,
      approved: true,
      approved_percent: null,
      approved_by_name: '',
      approved_at: null,
    },
    note: '',
    currency: 'CNY',
    lines: [line],
    line_count: 1,
    subtotal: '2000.00',
    discount_amount: '0.00',
    total: '2000.00',
    updated_at: '2026-11-21T00:00:00Z',
    ...overrides,
  }
}

let quote: ReturnType<typeof makeQuote> | null = null
let posts: { url: string; body: Record<string, unknown> }[] = []
let rejectNextPost = false

const adapter: AxiosAdapter = async config => {
  const url = config.url!.replace(/^\/api/, '')
  const method = config.method ?? 'get'
  if (method === 'post' || method === 'patch') {
    const body = config.data ? JSON.parse(String(config.data)) : {}
    posts.push({ url, body })
    if (rejectNextPost) {
      rejectNextPost = false
      return Promise.reject({
        response: { status: 409, data: { code: 'quote_outdated' } },
      })
    }
    if (url.endsWith('/quote/lines/')) {
      return { data: makeQuote(), status: 201, statusText: 'Created', headers: {}, config }
    }
    if (url.endsWith('/discount-approval/')) {
      return {
        data: makeQuote({
          discount_percent: '20.00',
          discount_approval: {
            threshold_percent: '15.00',
            required: true,
            approved: true,
            approved_percent: '20.00',
            approved_by_name: '管理员',
            approved_at: '2026-11-21T00:00:00Z',
          },
        }),
        status: 200, statusText: 'OK', headers: {}, config,
      }
    }
    return { data: makeQuote(), status: 200, statusText: 'OK', headers: {}, config }
  }
  if (url.startsWith('/price-book/')) {
    return {
      data: { count: 1, next: null, previous: null, results: [entry] },
      status: 200, statusText: 'OK', headers: {}, config,
    }
  }
  return {
    data: quote ?? { opportunity: 7, quote: null },
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

async function mountPanel(canWrite = true) {
  const wrapper = mount(QuotePanel, {
    props: { opportunityId: 7, canWrite },
    global: { plugins: [ElementPlus] },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  posts = []
  quote = null
  rejectNextPost = false
  setActivePinia(createPinia())
  http.defaults.adapter = adapter
})

describe('quote panel', () => {
  it('adds the first line from the price book', async () => {
    signIn('sales')
    const wrapper = await mountPanel()

    expect(wrapper.text()).toContain('尚无报价行')
    await wrapper.get('[data-test="quote-quantity"]').setValue('2')
    await wrapper.get('[data-test="quote-add"]').trigger('click')
    await flushPromises()

    expect(posts[0].url).toBe('/opportunities/7/quote/lines/')
    expect(posts[0].body).toEqual({ price_book_entry: 11, quantity: '2' })
    wrapper.unmount()
  })

  it('shows the frozen unit price and the totals', async () => {
    quote = makeQuote()
    signIn('sales')
    const wrapper = await mountPanel()

    const row = wrapper.get('[data-test="quote-line-21"]').text()
    expect(row).toContain('1000.00')
    expect(row).toContain('2000.00')
    expect(wrapper.get('[data-test="quote-totals"]').text()).toContain('合计 2000.00')
    wrapper.unmount()
  })

  it('saves the discount the person typed', async () => {
    quote = makeQuote()
    signIn('sales')
    const wrapper = await mountPanel()

    await wrapper.get('[data-test="quote-discount"]').setValue('12')
    await wrapper.get('[data-test="quote-save-discount"]').trigger('click')
    await flushPromises()

    expect(posts[0]).toEqual({
      url: '/opportunities/7/quote/',
      body: { discount_percent: '12' },
    })
    wrapper.unmount()
  })

  it('marks a discount that needs approval, and only an admin can decide', async () => {
    quote = makeQuote({
      discount_percent: '20.00',
      discount_approval: {
        threshold_percent: '15.00',
        required: true,
        approved: false,
        approved_percent: null,
        approved_by_name: '',
        approved_at: null,
      },
    })
    signIn('sales')
    const seller = await mountPanel()
    expect(seller.get('[data-test="quote-pending"]').text()).toContain('待管理员批准')
    expect(seller.find('[data-test="quote-approve"]').exists()).toBe(false)
    seller.unmount()

    signIn('admin')
    const admin = await mountPanel()
    await admin.get('[data-test="quote-comment"]').setValue('首单让利')
    await admin.get('[data-test="quote-approve"]').trigger('click')
    await flushPromises()

    expect(posts[0]).toEqual({
      url: '/opportunities/7/quote/discount-approval/',
      body: { comment: '首单让利' },
    })
    expect(admin.text()).toContain('折扣已批准')
    admin.unmount()
  })

  it('offers a rebind when the quote belongs to an older draft', async () => {
    quote = makeQuote()
    signIn('sales')
    const wrapper = await mountPanel()
    rejectNextPost = true

    await wrapper.get('[data-test="quote-add"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="quote-outdated"]').exists()).toBe(true)

    await wrapper.get('[data-test="quote-rebind"]').trigger('click')
    await flushPromises()

    expect(posts.at(-1)!.url).toBe('/opportunities/7/quote/rebind/')
    wrapper.unmount()
  })

  it('hides every write control from a reader', async () => {
    quote = makeQuote()
    signIn('presales')
    const wrapper = await mountPanel(false)

    expect(wrapper.find('[data-test="quote-add"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="quote-discount"]').exists()).toBe(true)
    expect(
      (wrapper.get('[data-test="quote-discount"]').element as HTMLInputElement)
        .disabled,
    ).toBe(true)
    expect(wrapper.text()).toContain('SKU-1')
    wrapper.unmount()
  })
})
