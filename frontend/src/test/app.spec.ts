import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import App from '../App.vue'

describe('application entry', () => {
  it('renders the active route', () => {
    const wrapper = mount(App, { global: { stubs: { RouterView: { template: '<main>当前页面</main>' } } } })
    expect(wrapper.text()).toBe('当前页面')
  })
})
