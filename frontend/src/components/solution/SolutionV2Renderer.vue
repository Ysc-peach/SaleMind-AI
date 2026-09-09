<script setup lang="ts">
import { computed, ref } from 'vue'
import SolutionSourceDrawer from './SolutionSourceDrawer.vue'
import type { SafeSolutionSource, V2Claim, V2Payload } from '../../types/workflow'

const props=defineProps<{payload:V2Payload;sourceRegistry:SafeSolutionSource[];claimSources:Record<string,string[]>}>()
const activeClaim=ref<string|null>(null)
const claims=computed(()=>new Map(props.payload.claims.map(item=>[item.claim_id,item])))
const sourceMap=computed(()=>new Map(props.sourceRegistry.map(item=>[item.source_id,item])))
const activeSources=computed(()=>(activeClaim.value?props.claimSources[activeClaim.value]??[]:[]).map(id=>sourceMap.value.get(id)).filter((item):item is SafeSolutionSource=>!!item))
const claim=(id:string):V2Claim|undefined=>claims.value.get(id)
const hasSources=(id:string)=>!!props.claimSources[id]?.length
const typeLabel:Record<V2Claim['statement_type'],string>={customer_fact:'客户事实',enterprise_fact:'企业事实',proposal:'方案建议',assumption:'假设',unresolved:'待确认'}
</script>

<template>
  <nav class="solution-section-nav" aria-label="方案章节">
    <a v-for="item in [['summary','执行摘要'],['customer','客户背景'],['proposal','总体方案'],['architecture','系统架构'],['deployment','部署与集成'],['implementation','实施计划'],['risks','风险'],['acceptance','验收标准'],['milestones','里程碑'],['assumptions','假设'],['questions','待确认事项'],['scope','范围边界']]" :key="item[0]" :href="`#v2-${item[0]}`">{{item[1]}}</a>
  </nav>
  <section id="v2-summary" class="panel"><h2>执行摘要</h2><ul class="claim-list"><li v-for="id in payload.executive_summary" :key="id"><el-tag size="small">{{claim(id)?typeLabel[claim(id)!.statement_type]:''}}</el-tag><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看来源</button></li></ul></section>
  <section id="v2-customer" class="panel"><h2>客户背景</h2><ul class="claim-list"><li v-for="id in [...payload.customer_context.confirmed_claim_ids,...payload.customer_context.unresolved_claim_ids]" :key="id"><el-tag size="small">{{claim(id)?typeLabel[claim(id)!.statement_type]:''}}</el-tag><span>{{claim(id)?.text}}</span></li></ul></section>
  <section id="v2-proposal" class="panel"><h2>总体方案</h2><ul class="claim-list"><li v-for="id in payload.proposed_solution.overview_claim_ids" :key="id"><el-tag size="small">{{claim(id)?typeLabel[claim(id)!.statement_type]:''}}</el-tag><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看来源</button></li></ul><article v-for="group in payload.proposed_solution.capability_groups" :key="group.group_id"><h3>{{group.title}}</h3><p v-for="id in group.claim_ids" :key="id">{{claim(id)?.text}}</p></article></section>
  <section id="v2-architecture" class="panel"><h2>系统架构</h2><p v-for="id in payload.architecture.overview_claim_ids" :key="id">{{claim(id)?.text}}</p><article v-for="component in payload.architecture.components" :key="component.component_id"><h3>{{component.name}}</h3><p v-for="id in [...component.responsibility_claim_ids,...component.rationale_claim_ids,...component.interface_claim_ids]" :key="id">{{claim(id)?.text}}</p></article></section>
  <section id="v2-deployment" class="panel"><h2>部署与集成</h2><article v-for="block in payload.deployment_and_integration" :key="block.block_id"><h3>{{block.title}}</h3><p v-for="id in block.claim_ids" :key="id">{{claim(id)?.text}}</p></article></section>
  <section id="v2-implementation" class="panel"><h2>实施计划</h2><article v-for="phase in payload.implementation_plan.phases" :key="phase.phase_id"><h3>{{phase.name}}</h3><p v-for="id in [...phase.objective_claim_ids,...phase.task_claim_ids,...phase.deliverable_claim_ids]" :key="id">{{claim(id)?.text}}</p><p v-if="phase.timing_claim_id"><strong>时间：</strong>{{claim(phase.timing_claim_id)?.text}}</p></article></section>
  <section id="v2-risks" class="panel"><h2>风险</h2><article v-for="risk in payload.risks" :key="risk.risk_id"><p>{{claim(risk.condition_claim_id)?.text}}</p><p v-for="id in [...risk.impact_claim_ids,...risk.mitigation_claim_ids,...risk.trigger_claim_ids]" :key="id">{{claim(id)?.text}}</p></article></section>
  <section id="v2-acceptance" class="panel"><h2>验收标准</h2><p v-for="item in payload.acceptance_criteria" :key="item.criterion_id">{{claim(item.claim_id)?.text}}</p></section>
  <section id="v2-milestones" class="panel"><h2>里程碑</h2><article v-for="item in payload.milestones" :key="item.milestone_id"><h3>{{item.name}}</h3><p v-for="id in item.outcome_claim_ids" :key="id">{{claim(id)?.text}}</p><p v-if="item.timing_claim_id">{{claim(item.timing_claim_id)?.text}}</p></article></section>
  <section id="v2-assumptions" class="panel"><h2>假设</h2><p v-for="id in payload.assumptions" :key="id">{{claim(id)?.text}}</p></section>
  <section id="v2-questions" class="panel"><h2>待确认事项</h2><p v-for="item in payload.open_questions" :key="item.question_id">{{claim(item.unresolved_claim_id)?.text}}</p></section>
  <section id="v2-scope" class="panel"><h2>范围边界</h2><p v-for="item in payload.out_of_scope" :key="item.scope_id">{{claim(item.claim_id)?.text}}</p></section>
  <SolutionSourceDrawer :open="activeClaim!==null" :sources="activeSources" @close="activeClaim=null" />
</template>

<style scoped>
.solution-section-nav{position:sticky;top:0;z-index:5;display:flex;gap:8px;overflow-x:auto;margin:18px 0;padding:12px;background:#fff;border:1px solid #e1e6ef;border-radius:10px}.solution-section-nav a{white-space:nowrap;color:#365b95;text-decoration:none}.claim-list{display:grid;gap:14px;padding:0;list-style:none}.claim-list li{display:flex;align-items:flex-start;gap:10px}.source-link{margin-left:auto;border:0;background:none;color:#315f9d;cursor:pointer;white-space:nowrap}
</style>
