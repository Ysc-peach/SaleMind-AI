import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import { http } from '../api/http'
import { useAuthStore } from '../stores/auth'
import SolutionDetail from '../views/SolutionDetailView.vue'

let draft:any, requests:number, exportReply:any, delayed:undefined|(()=>void)
let createURL:ReturnType<typeof vi.fn>, revokeURL:ReturnType<typeof vi.fn>
let click:ReturnType<typeof vi.spyOn>
beforeEach(()=>{
  setActivePinia(createPinia())
  const auth=useAuthStore();auth.restored=true;auth.accessToken='test-access'
  auth.user={id:1,username:'sales',role:'sales',email:'',first_name:'',last_name:''}
  draft={id:151,opportunity:242,analysis_id:298,version:2,schema_version:1,title:'内部技术方案',review_status:'approved',is_stale:false,stale_reasons:[],created_by:1,created_at:'2026-10-14T00:00:00Z',
    draft_payload:{title:'内部技术方案',executive_summary:[],solution_sections:[],assumptions:[]},provenance:[]}
  requests=0;delayed=undefined;exportReply=undefined
  createURL=vi.fn(()=> 'blob:export');revokeURL=vi.fn()
  vi.stubGlobal('URL',Object.assign(URL,{createObjectURL:createURL,revokeObjectURL:revokeURL}))
  click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{})
  http.defaults.adapter=async config=>{
    let data:any
    if(config.url?.endsWith('/export/')){
      requests++
      if(delayed) await new Promise<void>(r=>{delayed=r})
      if(exportReply?.error)throw {config,response:{status:exportReply.status,data:exportReply.data}}
      const type=config.params.file_type
      data=exportReply?.data??new Blob([type==='pdf'?'%PDF-verified':'PK\x03\x04verified'],{type:type==='pdf'?'application/pdf':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'})
      return {data,status:200,statusText:'OK',headers:{'content-type':data.type},config}
    }
    if(config.url?.endsWith('reviews/'))data={results:[]}
    else if(config.url?.startsWith('/opportunities/'))data={id:242,sales_owner:1,presales_owner:3}
    else data=draft
    return {data,status:200,statusText:'OK',headers:{},config}
  }
})
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals()})
async function page(){
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/solutions/:id',component:SolutionDetail},{path:'/opportunities/:id',component:{template:'<div />'}}]})
  await router.push('/solutions/151')
  const wrapper=mount(SolutionDetail,{global:{plugins:[router,ElementPlus]}})
  await flushPromises()
  return {wrapper,router}
}
async function settled(){await new Promise(r=>setTimeout(r,30));await flushPromises()}

it.each(['pdf','docx'])('approved_current_version_offers_%s_download',async kind=>{
  const {wrapper}=await page()
  await wrapper.get(`[data-test="export-${kind}"]`).trigger('click');await settled()
  expect(requests).toBe(1);expect(createURL).toHaveBeenCalledOnce()
  expect(click).toHaveBeenCalledOnce()
  wrapper.unmount()
})
it.each(['draft','pending_review','needs_revision','stale'])('disables_export_for_%s',async status=>{
  if(status==='stale')draft.is_stale=true;else draft.review_status=status
  const {wrapper}=await page()
  expect(wrapper.get('[data-test="export-pdf"]').attributes('disabled')).toBeDefined()
  expect(requests).toBe(0);wrapper.unmount()
})
it('double_click_is_one_request',async()=>{
  delayed=()=>{}
  const {wrapper}=await page()
  await wrapper.get('[data-test="export-pdf"]').trigger('click')
  await wrapper.get('[data-test="export-pdf"]').trigger('click');await flushPromises()
  expect(requests).toBe(1);delayed?.();await settled();wrapper.unmount()
})
it.each(['application/json','text/html','application/pdf'])('binary_error_content_%s_is_not_saved',async mime=>{
  exportReply={data:new Blob(['{"private":"PRIVATE_ERROR"}'],{type:mime})}
  const {wrapper}=await page()
  await wrapper.get('[data-test="export-pdf"]').trigger('click');await settled()
  expect(click).not.toHaveBeenCalled();expect(wrapper.text()).not.toContain('PRIVATE_ERROR')
  expect(wrapper.text()).toContain('导出');wrapper.unmount()
})
it('error_blob_is_controlled_message_without_server_text',async()=>{
  exportReply={error:true,status:409,data:new Blob([JSON.stringify({code:'solution_export_changed',message:'PRIVATE_TEXT'})],{type:'application/json'})}
  const {wrapper}=await page()
  await wrapper.get('[data-test="export-pdf"]').trigger('click');await settled()
  expect(wrapper.text()).toContain('刷新');expect(wrapper.text()).not.toContain('PRIVATE_TEXT')
  expect(wrapper.text()).not.toContain('重复提交生成');expect(click).not.toHaveBeenCalled();wrapper.unmount()
})
it('unknown_export_code_uses_download_error_not_generation_fallback',async()=>{
  exportReply={error:true,status:503,data:new Blob(['{"code":"solution_export_unknown","message":"PRIVATE_TEXT"}'],{type:'application/json'})}
  const {wrapper}=await page()
  await wrapper.get('[data-test="export-pdf"]').trigger('click');await settled()
  expect(wrapper.text()).toContain('暂时无法导出')
  expect(wrapper.text()).not.toContain('重复提交生成');wrapper.unmount()
})
it.each(['logout','same_account_relogin','route','refresh','unmount'])('suppresses_old_download_after_%s',async action=>{
  delayed=()=>{}
  const {wrapper,router}=await page()
  await wrapper.get('[data-test="export-pdf"]').trigger('click');await flushPromises()
  if(action==='logout'||action==='same_account_relogin'){
    const auth=useAuthStore();const user=auth.user;auth.logout();if(action==='same_account_relogin')auth.user=user
  }else if(action==='route')await router.push('/solutions/152')
  else if(action==='unmount')wrapper.unmount()
  else await wrapper.findAll('button').find(b=>b.text()==='刷新')!.trigger('click')
  delayed?.();await settled();expect(click).not.toHaveBeenCalled()
  if(action!=='unmount')wrapper.unmount()
})
it('url_is_released_after_the_click_failure_is_observed',async()=>{
  vi.useFakeTimers()
  try{
    const {saveDownload}=await import('../utils/download')
    click.mockImplementationOnce(()=>{throw new Error('blocked')})
    expect(()=>saveDownload(new Blob(['%PDF-']), 'file.pdf')).toThrow()
    expect(revokeURL).not.toHaveBeenCalled()
    vi.advanceTimersByTime(999)
    expect(revokeURL).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(revokeURL).toHaveBeenCalledWith('blob:export')
  }finally{vi.useRealTimers()}
})
it('url_survives_the_click_until_the_browser_can_consume_it',async()=>{
  vi.useFakeTimers()
  try{
    const {saveDownload}=await import('../utils/download')
    saveDownload(new Blob(['%PDF-']), 'file.pdf')
    expect(click).toHaveBeenCalledOnce()
    expect(revokeURL).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1000)
    expect(revokeURL).toHaveBeenCalledWith('blob:export')
  }finally{vi.useRealTimers()}
})
