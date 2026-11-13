<script setup lang="ts">
import { ref, watch, computed, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { analysisHistory, getAnalysis, latestAnalysis, createAnalysis } from '../api/analysis'
import { newWorkflowRequestKey, startSolutionWorkflow, waitForSolutionDraft } from '../api/workflows'
import type { Analysis, AnalysisSummary } from '../types/workflow'
import { safeError, generationNextAction } from '../utils/errors'
import { label, dateTime } from '../utils/labels'
import Notice from './Notice.vue'
const props=defineProps<{opportunityId:number}>(), router=useRouter()
const rows=ref<AnalysisSummary[]>([]), selected=ref(''), detail=ref<Analysis>(), latest=ref<Analysis>()
const loading=ref(false), busy=ref(false), error=ref(''), feedback=ref(''), page=ref(1), total=ref(0)
const pendingWorkflowKey=ref('')
const nextAction=ref<ReturnType<typeof generationNextAction>>()
const pendingFields=computed(()=>Object.entries(detail.value?.requirements??{})
  .filter(([,dimension])=>['unknown','unclear','conflict'].includes(dimension.status))
  .map(([field])=>label(field)))
function clearError(){error.value='';nextAction.value=undefined}
function reportError(value:unknown){error.value=safeError(value);nextAction.value=generationNextAction(value)}
let request=0, alive=true
onBeforeUnmount(()=>{alive=false; request++})
async function load() {
  loading.value=true; clearError()
  try { const data=await analysisHistory(props.opportunityId,page.value); if(alive){rows.value=data.results; total.value=data.count}; return true }
  catch(e){if(alive)reportError(e); return false} finally{if(alive)loading.value=false}
}
async function viewLatest(){clearError(); try{latest.value=await latestAnalysis(props.opportunityId)}catch(e){reportError(e)}}
watch(selected,async value=>{
  const current=++request; detail.value=undefined; clearError()
  if(!value)return
  try { const data=await getAnalysis(props.opportunityId,Number(value)); if(current===request)detail.value=data }
  catch(e){if(current===request)reportError(e)}
})
async function analyze(){
  if(busy.value)return; busy.value=true; clearError(); feedback.value=''
  try {
    const created=await createAnalysis(props.opportunityId)
    if(alive){
      const refreshFirstPage=page.value!==1
      rows.value=[created,...(refreshFirstPage?[]:rows.value.filter(item=>item.id!==created.id))]
      total.value+=1; page.value=1; latest.value=created; selected.value=''; detail.value=undefined
      const refreshed=!refreshFirstPage||await load()
      feedback.value=refreshed?`分析快照 #${created.id} 已创建。`:`分析快照 #${created.id} 已创建；历史列表暂未刷新，请稍后重新进入本页确认。`
      if(!refreshed)clearError()
    }
  }
  catch(e){if(alive)reportError(e)} finally{if(alive)busy.value=false}
}
async function generate(){
  if(busy.value||!detail.value||Number(selected.value)!==detail.value.id)return
  busy.value=true; clearError()
  try {
    pendingWorkflowKey.value ||= newWorkflowRequestKey()
    const started=await startSolutionWorkflow(props.opportunityId,detail.value.id,pendingWorkflowKey.value)
    // Async mode answers 202 with no draft yet; the worker fills it in later.
    const result=await waitForSolutionDraft(started)
    if(!result.solution_draft_id){
      if(alive)reportError({response:{status:422,data:{code:result.error_code||'workflow_failed'}}})
      return
    }
    if(alive){pendingWorkflowKey.value='';await router.push(`/solutions/${result.solution_draft_id}`)}
  }
  catch(e){if(alive)reportError(e)} finally{if(alive)busy.value=false}
}
watch(()=>props.opportunityId,()=>{selected.value='';detail.value=undefined;latest.value=undefined;feedback.value='';pendingWorkflowKey.value='';page.value=1;load()},{immediate:true})
watch(selected,()=>{pendingWorkflowKey.value=''})
function changePage(nextPage:number){selected.value='';detail.value=undefined;feedback.value='';page.value=nextPage;load()}
</script>
<template><section class="panel"><div class="page-heading"><div><h2>AI需求分析</h2><p class="muted">分析是不可修改的快照。请明确选择一个快照，再生成技术方案。</p></div><el-button :disabled="busy||loading" @click="analyze">创建新分析</el-button></div>
<Notice :error="error" :loading="loading" /><p v-if="feedback" role="status" class="notice">{{feedback}}</p><p v-if="busy" role="status" class="notice">AI 正在处理，请勿重复操作。方案校验可能需要约一分钟；生成后仍为草稿，不会自动提交审核。</p>
<p v-if="error&&nextAction"><RouterLink data-test="generation-next-action" :to="{path:`/opportunities/${opportunityId}`,query:{tab:nextAction.tab}}">{{nextAction.label}}</RouterLink></p>
<div class="row"><label for="analysis-selection">生成依据</label><select id="analysis-selection" v-model="selected" :disabled="busy||loading"><option value="">请选择分析快照</option><option v-for="item in rows" :key="item.id" :value="String(item.id)">快照 #{{item.id}} · {{dateTime(item.created_at)}}</option></select><el-button :disabled="busy" @click="viewLatest">查看最新分析摘要</el-button></div>
<p v-if="latest" class="muted">最新快照 #{{latest.id}}：{{latest.summary}}（不会自动替换您的选择）</p>
<p v-if="!loading&&!rows.length&&!error" class="muted">尚无分析快照。请先保存客户需求，再创建分析。</p>
<el-pagination v-if="total>20" v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" :disabled="busy" @current-change="changePage" />
<template v-if="detail"><h3>快照 #{{detail.id}}</h3><p class="preserve">{{detail.summary}}</p><div class="dimension-grid"><article v-for="(dimension,key) in detail.requirements" :key="key" class="dimension"><h4>{{label(String(key))}} <el-tag size="small">{{label(dimension.status)}}</el-tag></h4><p class="preserve">{{dimension.value ?? '尚无已确认内容'}}</p><details v-if="dimension.evidence"><summary>需求依据</summary><blockquote>{{dimension.evidence}}</blockquote></details></article></div><div v-if="detail.conflicts.length"><h3>需要解决的信息冲突</h3><p v-for="(conflict,index) in detail.conflicts" :key="index">{{conflict.description}}</p></div><div v-if="detail.clarifying_questions.length"><h3>建议向客户确认</h3><p v-for="(question,index) in detail.clarifying_questions" :key="index">{{question.question}}</p></div></template>
<p v-if="detail&&pendingFields.length" class="notice" data-test="pending-information">所选快照仍有待确认信息：{{pendingFields.join('、')}}。并非所有待确认项都会阻塞生成；初步方案必须保留这些边界，不自行补充数值、能力或承诺。请查看上方的追问和冲突，仅依据客户真实反馈更新需求并创建新快照。</p>
<el-button type="primary" data-test="generate" :disabled="busy||!detail||Number(selected)!==detail.id" :loading="busy" @click="generate">基于所选快照生成方案</el-button></section></template>
