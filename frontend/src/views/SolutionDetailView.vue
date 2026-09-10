<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { getSolution } from '../api/solutions'
import { getOpportunity } from '../api/opportunities'
import { reviewHistory, submitReview, approveReview, returnReview } from '../api/reviews'
import { getSolutionWorkflow, resumeSolutionWorkflow } from '../api/workflows'
import type { Solution, SolutionV1, SolutionV2, Review, ReturnReason, SolutionWorkflow } from '../types/workflow'
import type { Opportunity } from '../types/domain'
import { safeError } from '../utils/errors'
import { label, dateTime } from '../utils/labels'
import Notice from '../components/Notice.vue'
import SolutionV1Renderer from '../components/solution/SolutionV1Renderer.vue'
import SolutionV2Renderer from '../components/solution/SolutionV2Renderer.vue'
import WorkflowProgress from '../components/workflow/WorkflowProgress.vue'
const route=useRoute(),auth=useAuthStore()
const draft=ref<Solution>(),opportunity=ref<Opportunity>(),reviews=ref<Review[]>([]),workflow=ref<SolutionWorkflow>(),loading=ref(false),busy=ref(false),error=ref(''),historyError=ref('')
const reason=ref<ReturnReason|''>(''),comment=ref(''),reviewerId=ref('')
const pending=computed(()=>reviews.value.find(r=>r.status==='pending'))
const ownOpportunity=computed(()=>!!opportunity.value&&(opportunity.value.sales_owner===auth.user?.id||opportunity.value.presales_owner===auth.user?.id))
const workflowAllows=(action:'SUBMIT_FOR_REVIEW'|'APPROVE'|'REQUEST_REVISION')=>!draft.value?.workflow_id||!!workflow.value?.allowed_actions.includes(action)
const canSubmit=computed(()=>draft.value?.review_status==='draft'&&!draft.value.is_stale&&workflowAllows('SUBMIT_FOR_REVIEW')&&(auth.user?.role==='admin'||ownOpportunity.value))
const independent=computed(()=>auth.user?.role==='presales'&&draft.value?.created_by===auth.user.id)
const needsExplicitReviewer=computed(()=>independent.value||(auth.user?.role==='admin'&&draft.value?.created_by===auth.user.id&&!opportunity.value?.presales_owner))
const canDecide=computed(()=>draft.value?.review_status==='pending_review'&&pending.value&&workflowAllows('APPROVE')&&workflowAllows('REQUEST_REVISION')&&auth.user?.id!==draft.value.created_by&&(auth.user?.role==='admin'||(auth.user?.role==='presales'&&pending.value.reviewer===auth.user.id)))
let request=0
async function load(){
  const current=++request; loading.value=true;error.value='';historyError.value='';draft.value=undefined;reviews.value=[];workflow.value=undefined;opportunity.value=undefined
  try{
    const data=await getSolution(Number(route.params.id)); if(current!==request)return; draft.value=data
    // An independent reviewer may read the version without Opportunity visibility.
    const [history,context,workflowStatus]=await Promise.allSettled([
      reviewHistory(data.id),
      getOpportunity(data.opportunity),
      data.workflow_id?getSolutionWorkflow(data.workflow_id):Promise.resolve(undefined),
    ])
    if(current!==request)return
    if(history.status==='fulfilled')reviews.value=history.value;else historyError.value=safeError(history.reason)
    if(context.status==='fulfilled')opportunity.value=context.value
    if(workflowStatus.status==='fulfilled')workflow.value=workflowStatus.value
    else if(data.workflow_id)historyError.value=safeError(workflowStatus.reason)
  }catch(e){if(current===request)error.value=safeError(e)}finally{if(current===request)loading.value=false}
}
async function act(action:'submit'|'approve'|'return'){
  if(busy.value||!draft.value)return
  if(action==='return'&&(!reason.value||!comment.value.trim()))return
  busy.value=true;error.value=''
  try{
    if(draft.value.workflow_id){
      if(action==='submit')await resumeSolutionWorkflow(draft.value.workflow_id,{action:'SUBMIT_FOR_REVIEW'})
      if(action==='approve')await resumeSolutionWorkflow(draft.value.workflow_id,{action:'APPROVE'})
      if(action==='return')await resumeSolutionWorkflow(draft.value.workflow_id,{action:'REQUEST_REVISION',return_reason:(reason.value as ReturnReason).toUpperCase() as Uppercase<ReturnReason>,comment:comment.value.trim()})
    }else{
      if(action==='submit')await submitReview(draft.value.id,needsExplicitReviewer.value?Number(reviewerId.value):undefined)
      if(action==='approve')await approveReview(draft.value.id)
      if(action==='return')await returnReview(draft.value.id,reason.value as ReturnReason,comment.value.trim())
    }
    await load();comment.value='';reason.value=''
  }catch(e){
    const message=safeError(e)
    if((e as {response?:{status?:number}})?.response?.status===409)await load()
    error.value=message
  }finally{busy.value=false}
}
watch(()=>route.params.id,()=>{reason.value='';comment.value='';reviewerId.value='';load()},{immediate:true})
</script>
<template><Notice :loading="loading" :error="error" /><template v-if="draft"><RouterLink v-if="opportunity" :to="`/opportunities/${draft.opportunity}?tab=solutions`" class="back-link">← 商机工作区</RouterLink><div class="page-heading"><div><p class="eyebrow">SOLUTION V{{draft.version}} · 分析快照 #{{draft.analysis_id}}</p><h1>{{draft.title}}</h1><p class="muted">{{dateTime(draft.created_at)}} · 创建人 #{{draft.created_by}}</p></div><el-button :disabled="busy||loading" @click="load">刷新</el-button></div><div class="row status-row"><el-tag>{{label(draft.review_status)}}</el-tag><span :class="draft.is_stale?'stale-badge':'current-badge'">{{draft.is_stale?'已过期':'当前有效'}}</span></div><div v-if="draft.is_stale" class="notice"><strong>此版本需要重新核对依据</strong><p v-for="item in draft.stale_reasons" :key="item">{{label(item)}}</p><p>审核历史仍保留，过期状态不等于撤销历史批准。</p></div>
<WorkflowProgress v-if="workflow" :workflow="workflow" />
<SolutionV1Renderer v-if="draft.schema_version===1" :solution="draft as SolutionV1" />
<SolutionV2Renderer v-else-if="draft.schema_version===2" :payload="(draft as SolutionV2).draft_payload" :source-registry="(draft as SolutionV2).source_registry" :claim-sources="(draft as SolutionV2).claim_sources" />
<section v-else class="panel notice" data-test="unsupported-schema">此方案使用当前前端不支持的结构版本，请刷新应用或联系管理员。</section>
<section id="review" class="panel"><h2>技术审核</h2><p class="muted">通过表示当前版本可用于对外技术沟通，不表示客户成交或签约。</p><Notice :error="historyError" />
<div v-if="canSubmit&&!loading"><template v-if="needsExplicitReviewer"><label for="independent-reviewer">独立审核人 ID</label><input id="independent-reviewer" v-model="reviewerId" type="number" min="1" :disabled="busy" /><p class="muted">当前版本需由另一名售前或业务管理员审核。请填写已有审核人 ID，最终资格由服务端检查。</p></template><el-button data-test="submit" type="primary" :disabled="busy||(needsExplicitReviewer&&(!Number.isInteger(Number(reviewerId))||Number(reviewerId)<=0||Number(reviewerId)===auth.user?.id))" @click="act('submit')">提交售前审核</el-button></div>
<div v-if="canDecide&&!loading" class="review-form"><el-button data-test="approve" type="primary" :disabled="busy||draft.is_stale" @click="act('approve')">通过技术审核</el-button><h3>退回处理</h3><label for="return-reason">退回原因（必填）</label><select id="return-reason" v-model="reason" data-test="reason" :disabled="busy"><option value="">请选择处理方向</option><option value="customer_info_required">需要补充客户信息</option><option value="technical_revision_required">需要修改技术方案</option></select><p class="muted">{{reason==='technical_revision_required'?'由售前完善技术方案并创建新版本，不修改旧版本正文。':'由销售向客户核实事实，再创建新的分析快照和方案版本。'}}</p><label for="return-comment">处理意见（必填）</label><textarea id="return-comment" v-model="comment" rows="4" :disabled="busy" /><el-button data-test="return" :disabled="busy||!reason||!comment.trim()" @click="act('return')">确认退回处理</el-button></div>
<p v-if="!loading&&!historyError&&!reviews.length" class="muted">尚未提交审核。请先检查方案与来源。</p><article v-for="review in reviews" :key="review.id" class="review-entry"><div class="row"><strong>{{label(review.status)}}</strong><span>审核人 #{{review.reviewer}}</span><span class="muted">{{dateTime(review.submitted_at)}}</span></div><p v-if="review.return_reason"><strong>{{label(review.return_reason)}}</strong></p><p v-if="review.comment" class="preserve">{{review.comment}}</p><p v-if="review.decided_at" class="muted">决策时间 {{dateTime(review.decided_at)}}</p></article></section></template></template>
