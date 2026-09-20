import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import ElementPlus from 'element-plus'
import AppShell from '../layouts/AppShell.vue'
import { useAuthStore } from '../stores/auth'

it('assigns distinct ownership classes to the application sidebar and content review panel', async () => {
  const pinia=createPinia()
  setActivePinia(pinia)
  const auth=useAuthStore()
  auth.restored=true
  auth.user={id:2,username:'presales',role:'presales',email:'',first_name:'',last_name:''}
  const reviewPage={template:'<aside class="solution-review-panel"><section class="panel">技术审核</section></aside>'}
  const placeholder={template:'<div />'}
  const router=createRouter({history:createMemoryHistory(),routes:[
    {path:'/',component:AppShell,children:[{path:'',component:reviewPage}]},
    {path:'/workspace',component:placeholder},
    {path:'/reviews',component:placeholder},
    {path:'/opportunities',component:placeholder},
  ]})
  await router.push('/')
  await router.isReady()
  const wrapper=mount(RouterView,{global:{plugins:[pinia,router,ElementPlus]}})

  const sidebar=wrapper.get('.app-sidebar')
  const shell=wrapper.get('.app-shell')
  const body=wrapper.get('.app-body')
  const content=wrapper.get('main.content')
  const reviewPanel=wrapper.get('.solution-review-panel')
  expect(shell.classes()).toContain('responsive-app-shell')
  expect(body.classes()).toContain('shrinkable-app-body')
  expect(content.classes()).toContain('shrinkable-main-content')
  expect(sidebar.element.tagName).toBe('ASIDE')
  expect(reviewPanel.element.tagName).toBe('ASIDE')
  expect(wrapper.find('.app-sidebar .solution-review-panel').exists()).toBe(false)
  expect(reviewPanel.get('.panel').text()).toBe('技术审核')
  wrapper.unmount()
})
