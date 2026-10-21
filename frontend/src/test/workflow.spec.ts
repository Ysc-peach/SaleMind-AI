import { beforeEach, expect, it } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import type { AxiosAdapter } from 'axios'
import { http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import AnalysisPanel from '../components/AnalysisPanel.vue'
import SolutionDetail from '../views/SolutionDetailView.vue'

const snapshot = { id: 14, summary: '合成需求快照', analysis_version: 'v1', created_at: '2026-09-08T00:00:00Z', requirements: { user_scale: { status: 'known', value: '300人', evidence: '需求原文' } }, conflicts: [], clarifying_questions: [] }
let draft: any, history: any[], calls: {url:string;method:string;body:any;params?:any}[], conflictAction:boolean, analysisTotal:number, opportunityContext:any
beforeEach(() => {
  setActivePinia(createPinia()); const auth = useAuthStore(); auth.restored = true
  auth.user = { id:1, username:'sales', role:'sales', email:'', first_name:'', last_name:'' }
  draft = { id:21, opportunity:7, analysis_id:14, version:1, schema_version:1, title:'合成技术方案', review_status:'draft', is_stale:false, stale_reasons:[], created_by:1, created_at:snapshot.created_at, draft_payload:{ title:'合成技术方案', executive_summary:[{type:'enterprise_fact', text:'支持私有化部署', citations:['K1']}], solution_sections:[], assumptions:[] }, provenance:[{citation_label:'K1', source_document_id:5, source_excerpt:'支持私有化部署', source_content_hash:'INTERNAL_HASH', source_index_run_id:'INTERNAL_RUN'}] }
  history = []; calls = []; conflictAction=false; analysisTotal=1; opportunityContext={id:7,sales_owner:1,presales_owner:2}
  http.defaults.adapter = async config => {
    const url = config.url!, method = config.method!, body = config.data ? JSON.parse(config.data) : undefined
    calls.push({url,method,body,params:config.params}); let data: any
    if(conflictAction&&/(submit|approve|request-revision)\/$/.test(url)) throw {config,response:{status:409,data:{code:'solution_review_invalid_state',message:'raw internal state'}}}
    if(url.endsWith('submit/')) { draft.review_status='pending_review'; history=[{id:31, reviewer:2, submitted_by:1, status:'pending', submitted_at:snapshot.created_at}]; data=history[0] }
    else if(url.endsWith('approve/')) { draft.review_status='approved'; history[0].status='approved'; data=history[0] }
    else if(url.endsWith('request-revision/')) { draft.review_status='needs_revision'; history[0]={...history[0], status:'returned', ...body}; data=history[0] }
    else if(url.endsWith('reviews/')) data={results:history}
    else if(url.endsWith('solution-workflows/')) data={workflow_id:'8de65214-6e04-4d32-a97a-8afc68483051',status:'WAITING_FOR_SALES_CONFIRMATION',solution_draft_id:21,solution_version:1,solution_review_id:null,reviewer_id:null,allowed_actions:['SUBMIT_FOR_REVIEW'],error_code:''}
    else if(url.includes('requirement-analyses/')) data = /(?:14|latest)\/$/.test(url) || method==='post' ? snapshot : {count:analysisTotal,results:[snapshot]}
    else if(url==='/opportunities/7/') data=opportunityContext
    else data=draft
    return {config, data:JSON.parse(JSON.stringify(data)), status:200, statusText:'OK',headers:{}}
  }
})
async function mountPage(component: any, props={}) {
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/solutions/:id',component:SolutionDetail},{path:'/opportunities/:id',component:{template:'<div>workspace</div>'}}]})
  await router.push('/solutions/21')
  const w=mount(component,{props,global:{plugins:[router,ElementPlus]}}); await flushPromises(); return w
}
it('requires explicit analysis selection, preserves its id and does not auto-submit review', async()=>{
  const w=await mountPage(AnalysisPanel,{opportunityId:7})
  expect(w.get('[data-test="generate"]').attributes('disabled')).toBeDefined()
  await w.get('select').setValue('14'); await flushPromises()
  expect(w.text()).toContain('300人')
  await w.get('[data-test="generate"]').trigger('click'); await flushPromises()
  expect(calls.find(c=>c.method==='post'&&c.url.endsWith('solution-workflows/'))?.body).toEqual({analysis_id:14})
  expect(calls.filter(c=>c.method==='get'&&c.url==='/solution-drafts/21/')).toHaveLength(0)
  expect(calls.some(c=>c.url.endsWith('submit/'))).toBe(false); w.unmount()
})
it.each([
  ['solution_draft_insufficient_approved_evidence', '可引用'],
  ['solution_needs_sales_clarification', '客户确认'],
  ['solution_needs_presales_involvement', '技术冲突'],
  ['solution_draft_not_grounded', '事实依据'],
  ['invalid_solution_grounding_input', '校验输入'],
  ['solution_grounding_invalid_response', '校验模型'],
  ['solution_draft_unqualified_precondition', '核验完成不等于条件满足'],
  ['solution_draft_unconfirmed_assertion', '断言'],
  ['solution_draft_expression_unclassified', '技术核对'],
  ['solution_draft_invalid_response', '格式'],
])('keeps a failed %s replay on the analysis page without a new request key', async(code, subject)=>{
  const base=http.defaults.adapter as AxiosAdapter
  const requestKeys:string[]=[]
  http.defaults.adapter=async config=>{
    if(config.method!=='post'||!config.url?.endsWith('solution-workflows/'))return base(config)
    requestKeys.push(String(config.headers.get('Idempotency-Key')))
    if(requestKeys.length===1)throw {config,response:{status:422,data:{code,message:'private provider text'}}}
    return {config,status:200,statusText:'OK',headers:{},data:{
      workflow_id:'8de65214-6e04-4d32-a97a-8afc68483051',status:'FAILED',
      solution_draft_id:null,solution_version:null,solution_review_id:null,reviewer_id:null,
      allowed_actions:[],error_code:code,
    }}
  }
  const w=await mountPage(AnalysisPanel,{opportunityId:7})
  await w.get('select').setValue('14');await flushPromises()
  const router=(w.vm as any).$router
  const before=router.currentRoute.value.fullPath
  await w.get('[data-test="generate"]').trigger('click');await flushPromises()
  expect(w.text()).toContain(subject)
  await w.get('[data-test="generate"]').trigger('click');await flushPromises()
  expect(w.text()).toContain(subject)
  expect(w.text()).not.toContain('private provider text')
  expect(router.currentRoute.value.fullPath).toBe(before)
  expect(requestKeys).toHaveLength(2)
  expect(requestKeys[0]).toBe(requestKeys[1])
  w.unmount()
})
it.each([
  ['solution_needs_sales_clarification', '查看并补充客户需求', 'requirement'],
  ['solution_needs_presales_involvement', '查看售前负责人', 'overview'],
])('provides a safe next action for %s without generating again', async(code, caption, tab)=>{
  const base=http.defaults.adapter as AxiosAdapter
  http.defaults.adapter=async config=>{
    if(config.method==='post'&&config.url?.endsWith('solution-workflows/'))
      throw {config,response:{status:422,data:{code,message:'private output'}}}
    return base(config)
  }
  const w=await mountPage(AnalysisPanel,{opportunityId:7})
  await w.get('select').setValue('14'); await flushPromises()
  await w.get('[data-test="generate"]').trigger('click'); await flushPromises()
  const action=w.get('[data-test="generation-next-action"]')
  expect(action.text()).toContain(caption)
  expect(action.attributes('href')).toBe(`/opportunities/7?tab=${tab}`)
  await action.trigger('click'); await flushPromises()
  expect((w.vm as any).$router.currentRoute.value.query.tab).toBe(tab)
  expect(w.text()).not.toContain('private output')
  w.unmount()
})
it('does not offer customer supplementation as the remedy for a grounding veto', async()=>{
  const base=http.defaults.adapter as AxiosAdapter
  http.defaults.adapter=async config=>{
    if(config.method==='post'&&config.url?.endsWith('solution-workflows/'))
      throw {config,response:{status:422,data:{code:'solution_draft_not_grounded'}}}
    return base(config)
  }
  const w=await mountPage(AnalysisPanel,{opportunityId:7})
  await w.get('select').setValue('14'); await flushPromises()
  await w.get('[data-test="generate"]').trigger('click'); await flushPromises()
  expect(w.find('[data-test="generation-next-action"]').exists()).toBe(false)
  expect(w.text()).toContain('不等同于客户信息缺失')
  w.unmount()
})
it('shows pending dimensions without blocking a ready-with-gaps snapshot', async()=>{
  const base=http.defaults.adapter as AxiosAdapter
  http.defaults.adapter=async config=>{
    const response=await base(config)
    if(config.url?.endsWith('requirement-analyses/14/')) response.data={...snapshot,
      requirements:{user_scale:{status:'unknown',value:null,evidence:null}},
      clarifying_questions:[{field:'user_scale',question:'请确认实际使用人数。'}],
    }
    return response
  }
  const w=await mountPage(AnalysisPanel,{opportunityId:7})
  await w.get('select').setValue('14'); await flushPromises()
  expect(w.get('[data-test="pending-information"]').text()).toContain('用户规模')
  expect(w.get('[data-test="pending-information"]').text()).toContain('并非所有待确认项都会阻塞')
  expect(w.get('[data-test="generate"]').attributes('disabled')).toBeUndefined()
  await w.get('[data-test="generate"]').trigger('click'); await flushPromises()
  expect((w.vm as any).$router.currentRoute.value.path).toBe('/solutions/21')
  w.unmount()
})
it('uses the successful analysis response without a second history read',async()=>{
  const w=await mountPage(AnalysisPanel,{opportunityId:7})
  expect(calls.filter(c=>c.method==='get'&&c.url.endsWith('requirement-analyses/'))).toHaveLength(1)
  await w.get('button').trigger('click'); await flushPromises()
  expect(calls.filter(c=>c.method==='get'&&c.url.endsWith('requirement-analyses/'))).toHaveLength(1)
  expect(w.text()).toContain('最新快照 #14'); w.unmount()
})
it('clears a snapshot selection when navigating analysis history pages',async()=>{
  analysisTotal=21; const w=await mountPage(AnalysisPanel,{opportunityId:7})
  await w.get('select').setValue('14'); await flushPromises(); expect(w.get('[data-test="generate"]').attributes('disabled')).toBeUndefined()
  w.findComponent({name:'ElPagination'}).vm.$emit('current-change',2); await flushPromises()
  expect((w.get('select').element as HTMLSelectElement).value).toBe('')
  expect(w.get('[data-test="generate"]').attributes('disabled')).toBeDefined(); w.unmount()
})
it('refreshes the first history page after creating an analysis from another page',async()=>{
  analysisTotal=41; const w=await mountPage(AnalysisPanel,{opportunityId:7})
  w.findComponent({name:'ElPagination'}).vm.$emit('current-change',2); await flushPromises()
  await w.get('button').trigger('click'); await flushPromises()
  const createdAt=calls.findIndex(c=>c.method==='post'&&c.url.endsWith('requirement-analyses/'))
  expect(calls.slice(createdAt+1).some(c=>c.method==='get'&&c.url.endsWith('requirement-analyses/')&&c.params?.page===1)).toBe(true)
  expect(w.text()).toContain('分析快照 #14 已创建'); w.unmount()
})
it('disables duplicate generation while the selected snapshot request is pending',async()=>{
  const w=await mountPage(AnalysisPanel,{opportunityId:7}); await w.get('select').setValue('14'); await flushPromises()
  const base=http.defaults.adapter as AxiosAdapter; let release:()=>void=()=>{}
  const gate=new Promise<void>(resolve=>{release=resolve})
  http.defaults.adapter=async config=>{if(config.method==='post'&&config.url?.endsWith('solution-workflows/'))await gate;return base(config)}
  const button=w.get('[data-test="generate"]'); await button.trigger('click'); await button.trigger('click')
  expect(button.attributes('disabled')).toBeDefined()
  expect(calls.filter(c=>c.method==='post'&&c.url.endsWith('solution-workflows/'))).toHaveLength(0)
  release(); await flushPromises()
  expect(calls.filter(c=>c.method==='post'&&c.url.endsWith('solution-workflows/'))).toHaveLength(1); w.unmount()
})
it('renders structured content and scoped source, without internal provenance identifiers',async()=>{
  const w=await mountPage(SolutionDetail)
  expect(w.text()).toContain('支持私有化部署'); expect(w.text()).toContain('草稿'); expect(w.text()).toContain('文档 #5')
  expect(w.text()).not.toContain('INTERNAL_HASH'); expect(w.text()).not.toContain('INTERNAL_RUN'); w.unmount()
})
it('fails closed with a safe message for an unsupported persisted schema',async()=>{
  draft.schema_version=99
  const w=await mountPage(SolutionDetail)
  expect(w.get('[data-test="unsupported-schema"]').text()).toContain('不支持的结构版本')
  expect(w.text()).not.toContain('[object Object]')
  w.unmount()
})
it('stale draft renders reasons and cannot offer submit',async()=>{
  draft.is_stale=true; draft.stale_reasons=['newer_requirement_analysis']
  const w=await mountPage(SolutionDetail); expect(w.text()).toContain('存在更新的需求分析')
  expect(w.find('[data-test="submit"]').exists()).toBe(false); w.unmount()
})
it('Sales explicitly submits and reloads authoritative draft/history',async()=>{
  const w=await mountPage(SolutionDetail); await w.get('[data-test="submit"]').trigger('click'); await flushPromises()
  expect(w.text()).toContain('等待售前审核'); expect(w.find('[data-test="approve"]').exists()).toBe(false)
  expect(calls.filter(c=>c.url.endsWith('reviews/')).length).toBe(2); w.unmount()
})
function pending() { draft.review_status='pending_review'; history=[{id:31,reviewer:2,submitted_by:1,status:'pending',submitted_at:snapshot.created_at}] }
it('assigned Presales approves, Sales never sees decision actions',async()=>{
  pending(); const auth=useAuthStore(); auth.user!.id=2; auth.user!.role='presales'
  const w=await mountPage(SolutionDetail); await w.get('[data-test="approve"]').trigger('click'); await flushPromises()
  expect(w.text()).toContain('技术审核已通过'); expect(calls.some(c=>c.url.endsWith('approve/'))).toBe(true); w.unmount()
})
it.each(['customer_info_required','technical_revision_required'])('return requires reason and comment, preserves %s',async reason=>{
  pending(); useAuthStore().user!.id=2; useAuthStore().user!.role='presales'
  const w=await mountPage(SolutionDetail)
  expect(w.get('[data-test="return"]').attributes('disabled')).toBeDefined()
  await w.get('[data-test="reason"]').setValue(reason)
  expect(w.get('[data-test="return"]').attributes('disabled')).toBeDefined()
  await w.get('textarea').setValue('请补充确认信息'); await w.get('[data-test="return"]').trigger('click'); await flushPromises()
  expect(calls.find(c=>c.url.endsWith('request-revision/'))?.body).toEqual({return_reason:reason,comment:'请补充确认信息'}); w.unmount()
})
it('unrelated Presales does not see approve',async()=>{
  pending(); useAuthStore().user!.role='presales'; useAuthStore().user!.id=3
  const w=await mountPage(SolutionDetail); expect(w.find('[data-test="approve"]').exists()).toBe(false); w.unmount()
})
it('never presents self-review approval to the solution author',async()=>{
  pending(); history[0].reviewer=1; useAuthStore().user!.role='presales'
  const w=await mountPage(SolutionDetail); expect(w.find('[data-test="approve"]').exists()).toBe(false); w.unmount()
})
it('reloads authoritative state after an action conflict while preserving a safe message',async()=>{
  const w=await mountPage(SolutionDetail); conflictAction=true
  await w.get('[data-test="submit"]').trigger('click'); await flushPromises()
  expect(calls.filter(c=>c.url==='/solution-drafts/21/').length).toBe(2)
  expect(w.text()).toContain('当前状态不允许此操作')
  expect(w.text()).not.toContain('raw internal state'); w.unmount()
})
it('allows an Admin-authored draft without assigned Presales to choose an independent reviewer',async()=>{
  opportunityContext={id:7,sales_owner:4,presales_owner:null}; useAuthStore().user={id:1,username:'admin',role:'admin',email:'',first_name:'',last_name:''}
  const w=await mountPage(SolutionDetail); expect(w.find('#independent-reviewer').exists()).toBe(true)
  expect(w.get('[data-test="submit"]').attributes('disabled')).toBeDefined()
  await w.get('#independent-reviewer').setValue('2'); await w.get('[data-test="submit"]').trigger('click'); await flushPromises()
  expect(calls.find(c=>c.url.endsWith('submit/'))?.body).toEqual({reviewer_id:2}); w.unmount()
})
