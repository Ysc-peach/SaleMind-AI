<script setup lang="ts">
import { computed, ref } from 'vue'
import SolutionSourceDrawer from './SolutionSourceDrawer.vue'
import type { SafeSolutionSource, V2Claim, V2Payload } from '../../types/workflow'

const props=defineProps<{payload:V2Payload;sourceRegistry:SafeSolutionSource[];claimSources:Record<string,string[]>}>()
const activeClaim=ref<string|null>(null)
const claims=computed(()=>new Map(props.payload.claims.map(item=>[item.claim_id,item])))
const sourceMap=computed(()=>new Map(props.sourceRegistry.map(item=>[item.source_id,item])))
const activeSources=computed(()=>{
  const ids=activeClaim.value?props.claimSources[activeClaim.value]??[]:[]
  return [...new Set(ids)].map(id=>sourceMap.value.get(id)).filter((item):item is SafeSolutionSource=>!!item)
})
const activeClaimText=computed(()=>activeClaim.value?claims.value.get(activeClaim.value)?.text??'':'')
const claim=(id:string):V2Claim|undefined=>claims.value.get(id)
const sourceCount=(id:string)=>new Set((props.claimSources[id]??[]).filter(sourceId=>sourceMap.value.has(sourceId))).size
const hasSources=(id:string)=>sourceCount(id)>0
const typeLabel:Record<V2Claim['statement_type'],string>={customer_fact:'客户事实',enterprise_fact:'企业事实',proposal:'方案建议',assumption:'假设',unresolved:'待确认'}
</script>

<template>
  <nav class="solution-section-nav" data-test="solution-section-nav" aria-label="方案章节">
    <a v-for="item in [['summary','执行摘要'],['customer','客户背景'],['proposal','总体方案'],['architecture','系统架构'],['deployment','部署与集成'],['implementation','实施计划'],['risks','风险'],['acceptance','验收标准'],['milestones','里程碑'],['assumptions','假设'],['questions','待确认事项'],['scope','范围边界']]" :key="item[0]" :href="`#v2-${item[0]}`">{{item[1]}}</a>
  </nav>
  <section class="review-focus panel" data-test="review-focus" aria-labelledby="review-focus-title">
    <div class="review-focus-heading">
      <div><p class="eyebrow">REVIEW FOCUS</p><h2 id="review-focus-title">审核重点</h2></div>
      <div class="review-focus-counts"><span>{{payload.risks.length}} 项风险</span><span>{{payload.open_questions.length}} 项待确认</span><span>{{payload.acceptance_criteria.length}} 项验收条件</span></div>
    </div>
    <div class="review-focus-grid">
      <article><h3>主要风险</h3><p v-if="!payload.risks.length" class="muted">暂无明确风险项</p><a v-for="risk in payload.risks" :key="risk.risk_id" href="#v2-risks">{{claim(risk.condition_claim_id)?.text}}</a></article>
      <article><h3>待确认事项</h3><p v-if="!payload.open_questions.length" class="muted">暂无待确认事项</p><a v-for="item in payload.open_questions" :key="item.question_id" href="#v2-questions">{{claim(item.unresolved_claim_id)?.text}}</a></article>
      <article><h3>关键验收条件</h3><p v-if="!payload.acceptance_criteria.length" class="muted">暂无验收条件</p><a v-for="item in payload.acceptance_criteria" :key="item.criterion_id" href="#v2-acceptance">{{claim(item.claim_id)?.text}}</a></article>
    </div>
  </section>
  <section id="v2-summary" class="panel solution-section"><h2>执行摘要</h2><ul class="claim-list"><li v-for="id in payload.executive_summary" :key="id"><el-tag size="small">{{claim(id)?typeLabel[claim(id)!.statement_type]:''}}</el-tag><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看 {{sourceCount(id)}} 条来源</button></li></ul></section>
  <section id="v2-customer" class="panel solution-section"><h2>客户背景</h2><ul class="claim-list"><li v-for="id in [...payload.customer_context.confirmed_claim_ids,...payload.customer_context.unresolved_claim_ids]" :key="id"><el-tag size="small">{{claim(id)?typeLabel[claim(id)!.statement_type]:''}}</el-tag><span>{{claim(id)?.text}}</span></li></ul></section>
  <section id="v2-proposal" class="panel solution-section"><h2>总体方案</h2><ul class="claim-list"><li v-for="id in payload.proposed_solution.overview_claim_ids" :key="id"><el-tag size="small">{{claim(id)?typeLabel[claim(id)!.statement_type]:''}}</el-tag><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看 {{sourceCount(id)}} 条来源</button></li></ul><article v-for="group in payload.proposed_solution.capability_groups" :key="group.group_id"><h3>{{group.title}}</h3><p v-for="id in group.claim_ids" :key="id">{{claim(id)?.text}}<button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看 {{sourceCount(id)}} 条来源</button></p></article></section>
  <section id="v2-architecture" class="panel solution-section"><h2>系统架构</h2><p v-for="id in payload.architecture.overview_claim_ids" :key="id">{{claim(id)?.text}}<button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看 {{sourceCount(id)}} 条来源</button></p><article v-for="component in payload.architecture.components" :key="component.component_id"><h3>{{component.name}}</h3><p v-for="id in [...component.responsibility_claim_ids,...component.rationale_claim_ids,...component.interface_claim_ids]" :key="id">{{claim(id)?.text}}<button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看 {{sourceCount(id)}} 条来源</button></p></article></section>
  <section id="v2-deployment" class="panel solution-section"><h2>部署与集成</h2><article v-for="block in payload.deployment_and_integration" :key="block.block_id"><h3>{{block.title}}</h3><p v-for="id in block.claim_ids" :key="id">{{claim(id)?.text}}<button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看 {{sourceCount(id)}} 条来源</button></p></article></section>
  <section id="v2-implementation" class="panel solution-section"><h2>实施计划</h2><article v-for="phase in payload.implementation_plan.phases" :key="phase.phase_id"><h3>{{phase.name}}</h3><p v-for="id in [...phase.objective_claim_ids,...phase.task_claim_ids,...phase.deliverable_claim_ids]" :key="id">{{claim(id)?.text}}<button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看 {{sourceCount(id)}} 条来源</button></p><p v-if="phase.timing_claim_id"><strong>时间：</strong>{{claim(phase.timing_claim_id)?.text}}<button v-if="hasSources(phase.timing_claim_id)" :data-test="`sources-${phase.timing_claim_id}`" class="source-link" @click="activeClaim=phase.timing_claim_id">查看 {{sourceCount(phase.timing_claim_id)}} 条来源</button></p></article></section>
  <section id="v2-risks" class="panel solution-section"><h2>风险</h2><article v-for="risk in payload.risks" :key="risk.risk_id"><p>{{claim(risk.condition_claim_id)?.text}}<button v-if="hasSources(risk.condition_claim_id)" :data-test="`sources-${risk.condition_claim_id}`" class="source-link" @click="activeClaim=risk.condition_claim_id">查看 {{sourceCount(risk.condition_claim_id)}} 条来源</button></p><p v-for="id in [...risk.impact_claim_ids,...risk.mitigation_claim_ids,...risk.trigger_claim_ids]" :key="id">{{claim(id)?.text}}<button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看 {{sourceCount(id)}} 条来源</button></p></article></section>
  <section id="v2-acceptance" class="panel solution-section"><h2>验收标准</h2><p v-for="item in payload.acceptance_criteria" :key="item.criterion_id">{{claim(item.claim_id)?.text}}<button v-if="hasSources(item.claim_id)" :data-test="`sources-${item.claim_id}`" class="source-link" @click="activeClaim=item.claim_id">查看 {{sourceCount(item.claim_id)}} 条来源</button></p></section>
  <section id="v2-milestones" class="panel solution-section"><h2>里程碑</h2><article v-for="item in payload.milestones" :key="item.milestone_id"><h3>{{item.name}}</h3><p v-for="id in item.outcome_claim_ids" :key="id">{{claim(id)?.text}}<button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看 {{sourceCount(id)}} 条来源</button></p><p v-if="item.timing_claim_id">{{claim(item.timing_claim_id)?.text}}<button v-if="hasSources(item.timing_claim_id)" :data-test="`sources-${item.timing_claim_id}`" class="source-link" @click="activeClaim=item.timing_claim_id">查看 {{sourceCount(item.timing_claim_id)}} 条来源</button></p></article></section>
  <section id="v2-assumptions" class="panel solution-section"><h2>假设</h2><p v-for="id in payload.assumptions" :key="id">{{claim(id)?.text}}</p></section>
  <section id="v2-questions" class="panel solution-section"><h2>待确认事项</h2><p v-for="item in payload.open_questions" :key="item.question_id">{{claim(item.unresolved_claim_id)?.text}}</p></section>
  <section id="v2-scope" class="panel solution-section"><h2>范围边界</h2><p v-for="item in payload.out_of_scope" :key="item.scope_id">{{claim(item.claim_id)?.text}}<button v-if="hasSources(item.claim_id)" :data-test="`sources-${item.claim_id}`" class="source-link" @click="activeClaim=item.claim_id">查看 {{sourceCount(item.claim_id)}} 条来源</button></p></section>
  <SolutionSourceDrawer :open="activeClaim!==null" :claim-text="activeClaimText" :sources="activeSources" @close="activeClaim=null" />
</template>

<style scoped>
.solution-section-nav{position:sticky;top:0;z-index:5;display:flex;gap:8px;overflow-x:auto;margin:18px 0;padding:12px;background:rgba(255,255,255,.96);border:1px solid #e1e6ef;border-radius:10px;box-shadow:0 6px 18px rgba(31,45,71,.06)}.solution-section-nav a{white-space:nowrap;color:#365b95;text-decoration:none;padding:4px 6px}.solution-section{scroll-margin-top:72px}.review-focus{border-color:#cfdcf0;background:linear-gradient(135deg,#fff,#f5f8fd)}.review-focus-heading{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}.review-focus-heading h2{margin-top:4px}.review-focus-counts{display:flex;gap:8px;flex-wrap:wrap}.review-focus-counts span{padding:5px 9px;border-radius:999px;background:#e8f0fc;color:#315f9d;font-size:12px;font-weight:600}.review-focus-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.review-focus-grid article{padding:16px;border:1px solid #dde5f0;border-radius:9px;background:#fff}.review-focus-grid h3{margin-top:0}.review-focus-grid a{display:block;margin-top:10px;line-height:1.55;color:#314a6c}.claim-list{display:grid;gap:14px;padding:0;list-style:none}.claim-list li{display:flex;align-items:flex-start;gap:10px}.source-link{margin-left:8px;border:0;background:none;color:#315f9d;cursor:pointer;white-space:nowrap;font-size:13px}.source-link:hover{text-decoration:underline}@media(max-width:900px){.review-focus-heading{display:block}.review-focus-grid{grid-template-columns:1fr}.solution-section-nav{top:0}}
</style>
