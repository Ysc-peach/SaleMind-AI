import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import type { AxiosAdapter } from 'axios'
import CustomerDirectoryView from '../views/CustomerDirectoryView.vue'
import { http } from '../api/http'

const customer = {
  id: 7,
  name: 'Acme',
  industry: 'Manufacturing',
  company_size: '200-500',
  basic_info: '',
  opportunities: [],
}

let patches: { url: string; body: Record<string, unknown> }[] = []

const adapter: AxiosAdapter = async config => {
  const url = config.url!.replace(/^\/api/, '')
  if (config.method === 'patch') {
    patches.push({ url, body: JSON.parse(String(config.data)) })
    return {
      data: { ...customer, ...JSON.parse(String(config.data)) },
      status: 200, statusText: 'OK', headers: {}, config,
    }
  }
  return {
    data: { count: 1, next: null, previous: null, results: [customer] },
    status: 200, statusText: 'OK', headers: {}, config,
  }
}

beforeEach(() => {
  patches = []
  http.defaults.adapter = adapter
})

async function mountAndSearch() {
  const wrapper = mount(CustomerDirectoryView, { global: { plugins: [ElementPlus] } })
  await wrapper.get('input[placeholder="输入客户名称"]').setValue('Acme')
  await wrapper.get('.panel .row button').trigger('click')
  await flushPromises()
  return wrapper
}

describe('customer record editing', () => {
  it('sends only the edited fields and reports the refreshed name', async () => {
    const wrapper = await mountAndSearch()

    await wrapper.get('[data-test="edit-7"]').trigger('click')
    expect((wrapper.get('[data-test="edit-industry"]').element as HTMLInputElement).value)
      .toBe('Manufacturing')

    await wrapper.get('[data-test="edit-industry"]').setValue('Industrial equipment')
    await wrapper.get('[data-test="edit-name"]').setValue('Acme Industrial')
    const save = wrapper.findAll('button').find(button => button.text() === '保存修改')!
    await save.trigger('click')
    await flushPromises()

    expect(patches).toEqual([{
      url: '/customers/7/',
      body: {
        name: 'Acme Industrial',
        industry: 'Industrial equipment',
        company_size: '200-500',
        basic_info: '',
      },
    }])
    expect(wrapper.text()).toContain('客户资料已更新')
    expect(wrapper.find('[data-test="customer-edit"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('does not submit a blank customer name', async () => {
    const wrapper = await mountAndSearch()

    await wrapper.get('[data-test="edit-7"]').trigger('click')
    await wrapper.get('[data-test="edit-name"]').setValue('   ')
    const save = wrapper.findAll('button').find(button => button.text() === '保存修改')!
    await save.trigger('click')
    await flushPromises()

    expect(patches).toHaveLength(0)
    wrapper.unmount()
  })
})
