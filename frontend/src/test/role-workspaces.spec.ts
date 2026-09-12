import { beforeEach, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import { http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import SalesWorkspace from '../views/SalesWorkspaceView.vue'
import PresalesWorkspace from '../views/PresalesWorkspaceView.vue'
import OpportunityList from '../views/OpportunityListView.vue'
import CustomerDirectory from '../views/CustomerDirectoryView.vue'

const opportunity = {
  id: 7,
  project_name: '企业知识平台',
  customer: 3,
  customer_name: '示例集团',
  sales_owner: 1,
  sales_owner_name: '销售小王',
  presales_owner: 2,
  presales_owner_name: '售前小李',
  stage: 'solution',
  status: 'active',
  budget: null,
  expected_launch_date: null,
  updated_at: '2026-09-11T00:00:00Z',
}
const task = {
  solution_draft_id: 21,
  opportunity_id: 7,
  project_name: opportunity.project_name,
  customer_name: opportunity.customer_name,
  solution_version: 2,
  workflow_id: '8de65214-6e04-4d32-a97a-8afc68483051',
  status: 'WAITING_FOR_SALES_CONFIRMATION',
  updated_at: opportunity.updated_at,
}
const salesWorkspace = {
  my_opportunities: [opportunity],
  tasks: {
    customer_info_required: [{...task, status:'CUSTOMER_INFO_REQUIRED'}],
    waiting_for_sales_confirmation: [task],
    waiting_for_presales_review: [{...task, status:'WAITING_FOR_PRESALES_REVIEW'}],
  },
  recently_updated: [opportunity],
}
const inbox = {
  pending_reviews: [{
    review_id:31,
    solution_draft_id:21,
    opportunity_id:7,
    project_name:opportunity.project_name,
    customer_name:opportunity.customer_name,
    solution_version:2,
    sales_owner_name:'销售小王',
    status:'WAITING_FOR_PRESALES_REVIEW',
    return_reason:'',
    comment:'',
    submitted_at:opportunity.updated_at,
    decided_at:null,
  }],
  technical_revisions: [{
    review_id:32,
    solution_draft_id:22,
    opportunity_id:7,
    project_name:'门户升级',
    customer_name:'示例集团',
    solution_version:1,
    sales_owner_name:'销售小王',
    status:'TECHNICAL_REVISION_REQUIRED',
    return_reason:'technical_revision_required',
    comment:'请调整高可用设计',
    submitted_at:opportunity.updated_at,
    decided_at:opportunity.updated_at,
  }],
  recent_reviews: [],
}
let calls: {url:string;method:string;body:any;params:any}[]
let failWorkspace = false

beforeEach(() => {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.restored = true
  auth.user = {id:1,username:'sales',role:'sales',email:'',first_name:'',last_name:''}
  calls = []
  failWorkspace = false
  http.defaults.adapter = async config => {
    const body = config.data ? JSON.parse(config.data) : undefined
    calls.push({url:config.url!,method:config.method!,body,params:config.params})
    if (failWorkspace && config.url === '/workspaces/sales/') {
      throw {config,response:{status:500,data:{detail:'private traceback'}}}
    }
    let data:any
    if (config.url === '/workspaces/sales/') data = salesWorkspace
    else if (config.url === '/reviews/inbox/') data = inbox
    else if (config.url === '/customers/search/') data = {count:1,next:null,previous:null,results:[{id:3,name:'示例集团',industry:'制造',company_size:'大型',basic_info:'',opportunities:[]}]}
    else if (config.url === '/customers/' && config.method === 'post') data = {id:8,...body}
    else if (config.url === '/users/presales-options/') data = [{id:2,username:'pre',first_name:'售前',last_name:'小李'}]
    else if (config.url === '/opportunities/' && config.method === 'post') data = {id:9,...body}
    else if (config.url === '/opportunities/') data = {count:1,next:null,previous:null,results:[opportunity]}
    else data = {}
    return {config,data:JSON.parse(JSON.stringify(data)),status:200,statusText:'OK',headers:{}}
  }
})

async function mountAt(component:any,path='/workspace') {
  const router=createRouter({history:createMemoryHistory(),routes:[
    {path:'/workspace',component},
    {path:'/opportunities',component:OpportunityList},
    {path:'/opportunities/:id',component:{template:'<div />'}},
    {path:'/solutions/:id',component:{template:'<div />'}},
    {path:'/customers',component:CustomerDirectory},
  ]})
  await router.push(path)
  const wrapper=mount(component,{global:{plugins:[router,ElementPlus]}})
  await flushPromises()
  return {wrapper,router}
}

it('Sales workspace makes each current task and next action discoverable', async () => {
  const {wrapper}=await mountAt(SalesWorkspace)
  expect(wrapper.text()).toContain('我的商机')
  expect(wrapper.text()).toContain('待补充客户信息')
  expect(wrapper.text()).toContain('待提交售前审核')
  expect(wrapper.text()).toContain('等待售前审核')
  expect(wrapper.text()).toContain('示例集团')
  expect(wrapper.text()).toContain('销售小王')
  expect(wrapper.find('a[href="/opportunities/7"]').exists()).toBe(true)
  expect(wrapper.find('a[href="/solutions/21"]').exists()).toBe(true)
  wrapper.unmount()
})

it('Sales can create a customer from a real workspace entry point', async () => {
  const {wrapper}=await mountAt(SalesWorkspace)
  await wrapper.get('[data-test="new-customer"]').trigger('click')
  await wrapper.get('[data-test="customer-name"]').setValue('新客户公司')
  await wrapper.get('[data-test="save-customer"]').trigger('click')
  await flushPromises()
  expect(calls.find(call=>call.url==='/customers/'&&call.method==='post')?.body.name).toBe('新客户公司')
  expect(wrapper.text()).toContain('客户已创建')
  wrapper.unmount()
})

it('Sales can search a customer and create an Opportunity', async () => {
  const {wrapper,router}=await mountAt(SalesWorkspace)
  await wrapper.get('[data-test="new-opportunity"]').trigger('click')
  await wrapper.get('[data-test="customer-query"]').setValue('示例')
  await wrapper.get('[data-test="search-customer"]').trigger('click')
  await flushPromises()
  await wrapper.get('[data-test="customer-select"]').setValue('3')
  await wrapper.get('[data-test="project-name"]').setValue('新建商机项目')
  await wrapper.get('[data-test="save-opportunity"]').trigger('click')
  await flushPromises()
  expect(calls.find(call=>call.url==='/opportunities/'&&call.method==='post')?.body).toMatchObject({project_name:'新建商机项目',customer:3})
  expect(router.currentRoute.value.path).toBe('/opportunities/9')
  wrapper.unmount()
})

it('Presales sees assigned reviews immediately and starts from the correct Solution', async () => {
  const auth=useAuthStore(); auth.user!.id=2; auth.user!.role='presales'
  const {wrapper}=await mountAt(PresalesWorkspace)
  expect(wrapper.text()).toContain('待审核方案')
  expect(wrapper.text()).toContain('需要技术修改')
  expect(wrapper.text()).toContain('销售小王')
  expect(wrapper.find('a[href="/solutions/21"]').text()).toContain('开始审核')
  expect(calls.find(call=>call.url==='/reviews/inbox/')?.params).toBeUndefined()
  wrapper.unmount()
})

it('Opportunity lists render business display names instead of database IDs', async () => {
  const {wrapper}=await mountAt(OpportunityList,'/opportunities')
  expect(wrapper.text()).toContain('示例集团')
  expect(wrapper.text()).toContain('销售小王')
  expect(wrapper.text()).toContain('售前小李')
  expect(wrapper.text()).not.toContain('客户 #3')
  expect(wrapper.text()).not.toContain('用户 #1')
  wrapper.unmount()
})

it('workspace handles empty and safe error states', async () => {
  salesWorkspace.my_opportunities=[]
  salesWorkspace.tasks.customer_info_required=[]
  salesWorkspace.tasks.waiting_for_sales_confirmation=[]
  salesWorkspace.tasks.waiting_for_presales_review=[]
  salesWorkspace.recently_updated=[]
  let mounted=await mountAt(SalesWorkspace)
  expect(mounted.wrapper.text()).toContain('目前没有待办')
  mounted.wrapper.unmount()

  failWorkspace=true
  mounted=await mountAt(SalesWorkspace)
  expect(mounted.wrapper.text()).toContain('请求未完成')
  expect(mounted.wrapper.text()).not.toContain('private traceback')
  mounted.wrapper.unmount()
})
