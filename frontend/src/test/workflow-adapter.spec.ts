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

function useV2Draft() {
  draft.schema_version = 2
  draft.draft_payload = {
    title:'合成技术方案',
    claims:[
      {claim_id:'C1',statement_type:'customer_fact',text:'客户需要企业知识查询。',citations:[],related_requirement_fields:[]},
      {claim_id:'C2',statement_type:'proposal',text:'建议采用知识服务组件。',citations:['S1'],related_requirement_fields:[]},
      {claim_id:'C3',statement_type:'unresolved',text:'上线日期待确认。',citations:[],related_requirement_fields:[]},
      {claim_id:'C4',statement_type:'proposal',text:'建议在验收前验证可用性目标。',citations:['S2'],related_requirement_fields:[]},
    ],
    executive_summary:['C1','C2'],
    customer_context:{confirmed_claim_ids:['C1'],unresolved_claim_ids:['C3'],requirement_fields:[]},
    proposed_solution:{overview_claim_ids:['C2'],capability_groups:[]},
    architecture:{overview_claim_ids:['C2'],components:[]},
    deployment_and_integration:[],
    implementation_plan:{phases:[]},
    risks:[{risk_id:'R1',condition_claim_id:'C3',impact_claim_ids:[],mitigation_claim_ids:['C4'],trigger_claim_ids:[]}],
    acceptance_criteria:[{criterion_id:'A1',claim_id:'C4',classification:'proposed'}],
    milestones:[],
    assumptions:[],
    open_questions:[{question_id:'Q1',requirement_field:'timeline',requirement_status:'unknown',unresolved_claim_id:'C3'}],
    out_of_scope:[],
  }
  draft.source_registry = [
    {source_id:'S1',document_id:5,document_title:'产品能力说明',source_excerpt:'支持知识服务组件。'},
    {source_id:'S2',document_id:6,document_title:'验收说明',source_excerpt:'验收目标需要协商。'},
  ]
  draft.claim_sources = {C2:['S1'],C4:['S2']}
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

it('summarizes the V2 review state and attention counts above the long document', async () => {
  useV2Draft()
  const wrapper = await mountDetail()

  const summary=wrapper.get('[data-test="solution-summary"]')
  expect(summary.text()).toContain('V1')
  expect(summary.text()).toContain('当前有效')
  expect(summary.text()).toContain('草稿')
  expect(summary.text()).toContain('1 项风险')
  expect(summary.text()).toContain('1 项待确认')
  expect(summary.text()).toContain('2 个来源')
  wrapper.unmount()
})

it('keeps review actions discoverable in a sticky review rail for the assigned reviewer', async () => {
  workflow.status = 'WAITING_FOR_PRESALES_REVIEW'; workflow.allowed_actions = ['APPROVE','REQUEST_REVISION']; workflow.solution_review_id = 31; workflow.reviewer_id = 2
  draft.review_status = 'pending_review'
  review = {id:31,solution_draft:21,submitted_by:1,reviewer:2,status:'pending',return_reason:'',comment:'',submitted_at:snapshot.created_at,decided_at:null}
  const auth = useAuthStore(); auth.user!.id = 2; auth.user!.role = 'presales'
  const wrapper = await mountDetail()

  const actions=wrapper.get('[data-test="review-actions"]')
  expect(actions.classes()).toContain('review-action-rail')
  expect(actions.classes()).toContain('solution-review-panel')
  expect(actions.get('[data-test="approve"]').text()).toContain('通过技术审核')
  expect(actions.get('[data-test="return"]').text()).toContain('退回')
  expect(actions.get('[data-test="reason"]').isVisible()).toBe(true)
  expect(actions.get('textarea').isVisible()).toBe(true)
  wrapper.unmount()
})

it('keeps stale and historical V1 states explicit without invoking the V2 renderer', async () => {
  draft.is_stale = true
  draft.stale_reasons = ['newer_requirement_analysis']
  draft.draft_payload.executive_summary = [{statement_type:'customer_fact',text:'历史方案摘要',citations:[]}]
  const wrapper = await mountDetail()

  expect(wrapper.get('[data-test="solution-summary"]').text()).toContain('已过期')
  expect(wrapper.text()).toContain('历史方案摘要')
  expect(wrapper.find('[data-test="review-focus"]').exists()).toBe(false)
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
