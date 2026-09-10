import { beforeEach, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import { http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import AnalysisPanel from '../components/AnalysisPanel.vue'
import SolutionDetail from '../views/SolutionDetailView.vue'

const workflowId = '8de65214-6e04-4d32-a97a-8afc68483051'
const snapshot = {
  id: 14,
  summary: '合成需求快照',
  analysis_version: 'v1',
  created_at: '2026-09-10T00:00:00Z',
  requirements: {},
  conflicts: [],
  clarifying_questions: [],
}
const opportunity = {
  id: 7,
  project_name: '合成售前项目',
  customer: 3,
  sales_owner: 1,
  presales_owner: 2,
  stage: 'solution',
  status: 'active',
  budget: null,
  expected_launch_date: null,
  updated_at: snapshot.created_at,
}

let draft: any
let review: any
let workflow: any
let calls: {url:string;method:string;body:any;headers:any}[]
let conflict = false

beforeEach(() => {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.restored = true
  auth.user = {id:1, username:'sales', role:'sales', email:'', first_name:'', last_name:''}
  draft = {
    id:21,
    opportunity:7,
    analysis_id:14,
    version:1,
    schema_version:1,
    workflow_id:workflowId,
    title:'合成技术方案',
    review_status:'draft',
    is_stale:false,
    stale_reasons:[],
    created_by:1,
    created_at:snapshot.created_at,
    draft_payload:{title:'合成技术方案',executive_summary:[],solution_sections:[],assumptions:[]},
    provenance:[],
  }
  review = undefined
  workflow = {
    workflow_id:workflowId,
    status:'WAITING_FOR_SALES_CONFIRMATION',
    solution_draft_id:21,
    solution_version:1,
    solution_review_id:null,
    reviewer_id:null,
    allowed_actions:['SUBMIT_FOR_REVIEW'],
    error_code:'',
  }
  calls = []
  conflict = false
  http.defaults.adapter = async config => {
    const body = config.data ? JSON.parse(config.data) : undefined
    calls.push({url:config.url!,method:config.method!,body,headers:config.headers})
    if (conflict && config.url?.endsWith('/resume/')) {
      throw {config,response:{status:409,data:{code:'workflow_decision_conflict',message:'raw graph state'}}}
    }
    let data:any
    if (config.url === '/opportunities/7/solution-workflows/' && config.method === 'post') data = workflow
    else if (config.url === `/solution-workflows/${workflowId}/resume/`) {
      if (body.action === 'SUBMIT_FOR_REVIEW') {
        draft.review_status = 'pending_review'
        review = {id:31,solution_draft:21,submitted_by:1,reviewer:2,status:'pending',return_reason:'',comment:'',submitted_at:snapshot.created_at,decided_at:null}
        workflow = {...workflow,status:'WAITING_FOR_PRESALES_REVIEW',solution_review_id:31,reviewer_id:2,allowed_actions:['APPROVE','REQUEST_REVISION']}
      } else if (body.action === 'APPROVE') {
        draft.review_status = 'approved'; review.status = 'approved'
        workflow = {...workflow,status:'APPROVED',allowed_actions:[]}
      } else {
        draft.review_status = 'needs_revision'
        review = {...review,status:'returned',return_reason:body.return_reason.toLowerCase(),comment:body.comment}
        workflow = {...workflow,status:body.return_reason,allowed_actions:[]}
      }
      data = workflow
    }
    else if (config.url === `/solution-workflows/${workflowId}/`) data = workflow
    else if (config.url === '/solution-drafts/21/') data = draft
    else if (config.url === '/solution-drafts/21/reviews/') data = {results:review?[review]:[]}
    else if (config.url === '/opportunities/7/') data = opportunity
    else if (config.url?.includes('requirement-analyses/')) data = /14\/$/.test(config.url) ? snapshot : {count:1,next:null,previous:null,results:[snapshot]}
    else data = workflow
    return {config,data:JSON.parse(JSON.stringify(data)),status:200,statusText:'OK',headers:{}}
  }
})

async function mountDetail() {
  const router = createRouter({history:createMemoryHistory(),routes:[
    {path:'/solutions/:id',component:SolutionDetail},
    {path:'/opportunities/:id',component:{template:'<div>workspace</div>'}},
  ]})
  await router.push('/solutions/21')
  const wrapper = mount(SolutionDetail,{global:{plugins:[router,ElementPlus]}})
  await flushPromises()
  return wrapper
}

it('starts a workflow with the explicit analysis and a retry-safe idempotency key', async () => {
  const router = createRouter({history:createMemoryHistory(),routes:[
    {path:'/solutions/:id',component:{template:'<div />'}},
    {path:'/:pathMatch(.*)*',component:{template:'<div />'}},
  ]})
  await router.push('/')
  const wrapper = mount(AnalysisPanel,{props:{opportunityId:7},global:{plugins:[router,ElementPlus]}})
  await flushPromises()
  await wrapper.get('select').setValue('14')
  await flushPromises()
  await wrapper.get('[data-test="generate"]').trigger('click')
  await flushPromises()

  const start = calls.find(call => call.url === '/opportunities/7/solution-workflows/')
  expect(start?.body).toEqual({analysis_id:14})
  expect(start?.headers.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/)
  expect(router.currentRoute.value.path).toBe('/solutions/21')
  expect(calls.some(call => call.url.endsWith('/submit/'))).toBe(false)
  wrapper.unmount()
})

it('restores the Sales confirmation state from status after loading the DRAFT', async () => {
  const wrapper = await mountDetail()

  expect(calls.some(call => call.url === `/solution-workflows/${workflowId}/`)).toBe(true)
  expect(wrapper.text()).toContain('方案已生成，等待提交售前审核')
  expect(wrapper.find('[data-test="submit"]').exists()).toBe(true)
  for (const technical of ['LangGraph','checkpoint','interrupt','thread_id']) {
    expect(wrapper.text()).not.toContain(technical)
  }
  wrapper.unmount()
})

it('Sales resumes the workflow to submit and sees the Presales wait state', async () => {
  const wrapper = await mountDetail()
  await wrapper.get('[data-test="submit"]').trigger('click')
  await flushPromises()

  const resume = calls.find(call => call.url.endsWith('/resume/'))
  expect(resume?.body).toEqual({action:'SUBMIT_FOR_REVIEW'})
  expect(wrapper.text()).toContain('等待售前审核')
  expect(review.status).toBe('pending')
  wrapper.unmount()
})

it('reload recovery uses workflow status rather than browser memory', async () => {
  workflow.status = 'WAITING_FOR_PRESALES_REVIEW'
  workflow.solution_review_id = 31
  workflow.reviewer_id = 2
  workflow.allowed_actions = ['APPROVE','REQUEST_REVISION']
  draft.review_status = 'pending_review'
  review = {id:31,solution_draft:21,submitted_by:1,reviewer:2,status:'pending',return_reason:'',comment:'',submitted_at:snapshot.created_at,decided_at:null}

  const wrapper = await mountDetail()

  expect(wrapper.text()).toContain('等待售前审核')
  expect(calls.filter(call => call.url === `/solution-workflows/${workflowId}/`)).toHaveLength(1)
  wrapper.unmount()
})

it('assigned Presales approves through the workflow resume endpoint', async () => {
  workflow.status = 'WAITING_FOR_PRESALES_REVIEW'; workflow.allowed_actions = ['APPROVE','REQUEST_REVISION']; workflow.solution_review_id = 31; workflow.reviewer_id = 2
  draft.review_status = 'pending_review'
  review = {id:31,solution_draft:21,submitted_by:1,reviewer:2,status:'pending',return_reason:'',comment:'',submitted_at:snapshot.created_at,decided_at:null}
  const auth = useAuthStore(); auth.user!.id = 2; auth.user!.role = 'presales'
  const wrapper = await mountDetail()

  await wrapper.get('[data-test="approve"]').trigger('click')
  await flushPromises()

  expect(calls.find(call => call.url.endsWith('/resume/'))?.body).toEqual({action:'APPROVE'})
  expect(wrapper.text()).toContain('技术审核已通过')
  wrapper.unmount()
})

it.each(['customer_info_required','technical_revision_required'] as const)(
  'sends %s as a typed workflow revision action',
  async reason => {
    workflow.status = 'WAITING_FOR_PRESALES_REVIEW'; workflow.allowed_actions = ['APPROVE','REQUEST_REVISION']; workflow.solution_review_id = 31; workflow.reviewer_id = 2
    draft.review_status = 'pending_review'
    review = {id:31,solution_draft:21,submitted_by:1,reviewer:2,status:'pending',return_reason:'',comment:'',submitted_at:snapshot.created_at,decided_at:null}
    const auth = useAuthStore(); auth.user!.id = 2; auth.user!.role = 'presales'
    const wrapper = await mountDetail()
    await wrapper.get('[data-test="reason"]').setValue(reason)
    await wrapper.get('textarea').setValue('请按业务方向处理')
    await wrapper.get('[data-test="return"]').trigger('click')
    await flushPromises()

    expect(calls.find(call => call.url.endsWith('/resume/'))?.body).toEqual({
      action:'REQUEST_REVISION',
      return_reason:reason.toUpperCase(),
      comment:'请按业务方向处理',
    })
    wrapper.unmount()
  },
)

it('a 409 conflict reloads authoritative workflow and draft state safely', async () => {
  const wrapper = await mountDetail()
  conflict = true
  await wrapper.get('[data-test="submit"]').trigger('click')
  await flushPromises()

  expect(calls.filter(call => call.url === `/solution-workflows/${workflowId}/`)).toHaveLength(2)
  expect(calls.filter(call => call.url === '/solution-drafts/21/')).toHaveLength(2)
  expect(wrapper.text()).toContain('当前状态不允许此操作')
  expect(wrapper.text()).not.toContain('raw graph state')
  wrapper.unmount()
})
