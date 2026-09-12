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
const v2Draft=computed(()=>(draft.value?.schema_version===2?draft.value as SolutionV2:undefined))
const sourceCount=computed(()=>new Set(v2Draft.value?.source_registry.map(source=>source.source_id)??[]).size)
const reviewStatusCopy=computed(()=>{
  if(!draft.value)return ''
  return {
    draft:'方案仍是草稿，检查完成后可提交售前审核。',
    pending_review:'方案正在等待指定售前完成技术审核。',
    approved:'当前版本已通过内部技术审核，可用于对外技术沟通。',
    needs_revision:'当前版本已退回，请按审核意见创建新的方案版本。',
  }[draft.value.review_status]??'请以当前业务状态为准。'
})
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
<template>
  <Notice :loading="loading" :error="error" />
  <template v-if="draft">
    <RouterLink v-if="opportunity" :to="`/opportunities/${draft.opportunity}?tab=solutions`" class="back-link">← 商机工作区</RouterLink>
    <div class="page-heading">
      <div>
        <p class="eyebrow">SOLUTION V{{draft.version}} · 分析快照 #{{draft.analysis_id}}</p>
        <h1>{{draft.title}}</h1>
        <p class="muted">{{dateTime(draft.created_at)}} · 创建人 #{{draft.created_by}}</p>
      </div>
      <el-button :disabled="busy||loading" @click="load">刷新</el-button>
    </div>

    <section class="solution-summary" data-test="solution-summary" aria-label="方案状态摘要">
      <div><span class="summary-label">方案版本</span><strong>V{{draft.version}}</strong></div>
      <div><span class="summary-label">有效性</span><strong :class="draft.is_stale?'summary-danger':'summary-success'">{{draft.is_stale?'已过期':'当前有效'}}</strong></div>
      <div><span class="summary-label">审核状态</span><strong>{{label(draft.review_status)}}</strong></div>
      <template v-if="v2Draft">
        <div><span class="summary-label">风险</span><strong>{{v2Draft.draft_payload.risks.length}} 项风险</strong></div>
        <div><span class="summary-label">待确认</span><strong>{{v2Draft.draft_payload.open_questions.length}} 项待确认</strong></div>
        <div><span class="summary-label">证据来源</span><strong>{{sourceCount}} 个来源</strong></div>
      </template>
    </section>

    <div v-if="draft.is_stale" class="notice">
      <strong>此版本需要重新核对依据</strong>
      <p v-for="item in draft.stale_reasons" :key="item">{{label(item)}}</p>
      <p>审核历史仍保留，过期状态不等于撤销历史批准。</p>
    </div>
    <WorkflowProgress v-if="workflow" :workflow="workflow" />

    <div class="solution-detail-layout">
      <main class="solution-document">
        <SolutionV1Renderer v-if="draft.schema_version===1" :solution="draft as SolutionV1" />
        <SolutionV2Renderer v-else-if="draft.schema_version===2" :payload="(draft as SolutionV2).draft_payload" :source-registry="(draft as SolutionV2).source_registry" :claim-sources="(draft as SolutionV2).claim_sources" />
        <section v-else class="panel notice" data-test="unsupported-schema">此方案使用当前前端不支持的结构版本，请刷新应用或联系管理员。</section>

        <section id="review-history" class="panel review-history">
          <h2>审核记录</h2>
          <Notice :error="historyError" />
          <p v-if="!loading&&!historyError&&!reviews.length" class="muted">尚无审核记录。</p>
          <article v-for="review in reviews" :key="review.id" class="review-entry">
            <div class="row"><strong>{{label(review.status)}}</strong><span>审核人 #{{review.reviewer}}</span><span class="muted">{{dateTime(review.submitted_at)}}</span></div>
            <p v-if="review.return_reason"><strong>{{label(review.return_reason)}}</strong></p>
            <p v-if="review.comment" class="preserve">{{review.comment}}</p>
            <p v-if="review.decided_at" class="muted">决策时间 {{dateTime(review.decided_at)}}</p>
          </article>
        </section>
      </main>

      <aside id="review" class="solution-review-panel review-action-rail" data-test="review-actions" aria-label="技术审核操作">
        <section class="panel review-action-card">
          <p class="eyebrow">REVIEW</p>
          <div class="review-action-heading"><h2>技术审核</h2><el-tag>{{label(draft.review_status)}}</el-tag></div>
          <p>{{reviewStatusCopy}}</p>
          <p class="muted">通过表示当前版本可用于对外技术沟通，不表示客户成交或签约。</p>

          <div v-if="canSubmit&&!loading">
            <template v-if="needsExplicitReviewer">
              <label for="independent-reviewer">独立审核人 ID</label>
              <input id="independent-reviewer" v-model="reviewerId" type="number" min="1" :disabled="busy" />
              <p class="muted">当前版本需由另一名售前或业务管理员审核。请填写已有审核人 ID，最终资格由服务端检查。</p>
            </template>
            <el-button data-test="submit" type="primary" :disabled="busy||(needsExplicitReviewer&&(!Number.isInteger(Number(reviewerId))||Number(reviewerId)<=0||Number(reviewerId)===auth.user?.id))" @click="act('submit')">提交售前审核</el-button>
          </div>

          <div v-if="canDecide&&!loading" class="review-form">
            <el-button data-test="approve" type="primary" :disabled="busy||draft.is_stale" @click="act('approve')">通过技术审核</el-button>
            <h3>退回处理</h3>
            <label for="return-reason">退回原因（必填）</label>
            <select id="return-reason" v-model="reason" data-test="reason" :disabled="busy">
              <option value="">请选择处理方向</option>
              <option value="customer_info_required">需要补充客户信息</option>
              <option value="technical_revision_required">需要修改技术方案</option>
            </select>
            <p class="muted">{{reason==='technical_revision_required'?'由售前完善技术方案并创建新版本，不修改旧版本正文。':'由销售向客户核实事实，再创建新的分析快照和方案版本。'}}</p>
            <label for="return-comment">处理意见（必填）</label>
            <textarea id="return-comment" v-model="comment" rows="4" :disabled="busy" />
            <el-button data-test="return" :disabled="busy||!reason||!comment.trim()" @click="act('return')">确认退回处理</el-button>
          </div>
        </section>
      </aside>
    </div>
  </template>
</template>

<style scoped>
.solution-summary{display:grid;grid-template-columns:repeat(6,minmax(110px,1fr));gap:1px;margin:16px 0 20px;overflow:hidden;border:1px solid #dfe6ef;border-radius:12px;background:#dfe6ef}.solution-summary>div{display:grid;gap:7px;padding:16px;background:#fff}.summary-label{font-size:12px;color:#64748b}.summary-success{color:#247044}.summary-danger{color:#9a6500}.solution-detail-layout{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:24px;align-items:start}.solution-document{min-width:0}.review-action-rail{position:sticky;top:20px;scroll-margin-top:20px}.review-action-card{margin-top:20px}.review-action-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.review-action-heading h2{margin-bottom:8px}.review-action-card .review-form{max-width:none}.review-action-card .el-button{width:100%}.review-history{scroll-margin-top:72px}@media(max-width:1100px){.solution-summary{grid-template-columns:repeat(3,1fr)}.solution-detail-layout{display:flex;flex-direction:column}.review-action-rail{position:static;order:-1;width:100%}.review-action-card{margin-bottom:0}}@media(max-width:600px){.solution-summary{grid-template-columns:repeat(2,1fr)}}
</style>
