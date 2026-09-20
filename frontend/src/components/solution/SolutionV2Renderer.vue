<script setup lang="ts">
import { computed, ref } from 'vue'
import SolutionSourceDrawer from './SolutionSourceDrawer.vue'
import { label } from '../../utils/labels'
import type { SafeSolutionSource, V2Claim, V2Payload } from '../../types/workflow'

const props=defineProps<{payload:V2Payload;sourceRegistry:SafeSolutionSource[];claimSources:Record<string,string[]>}>()
const activeClaim=ref<string|null>(null)
const claims=computed(()=>new Map(props.payload.claims.map(item=>[item.claim_id,item])))
const sourceMap=computed(()=>new Map(props.sourceRegistry.map(item=>[item.source_id,item])))
const componentTitle=(component:V2Payload['architecture']['components'][number])=>{
  if(!component.identity_claim_id)return component.name
  const identity=claims.value.get(component.identity_claim_id)
  return identity?.statement_type==='proposal'&&identity.text?identity.text:'组件名称不可用'
}
const componentNames=computed(()=>new Map(props.payload.architecture.components.map(item=>[item.component_id,componentTitle(item)])))
const architectureFlows=computed(()=>props.payload.architecture.flows??[])
const requestFlows=computed(()=>architectureFlows.value.filter(item=>item.flow_type==='request'))
const dataFlows=computed(()=>architectureFlows.value.filter(item=>item.flow_type==='data'))
const phaseNames=computed(()=>new Map(props.payload.implementation_plan.phases.map(item=>[item.phase_id,item.name])))
const acceptanceClaims=computed(()=>new Map(props.payload.acceptance_criteria.map(item=>[item.criterion_id,item.claim_id])))
const capabilityBasis=computed(()=>props.payload.proposed_solution.capability_groups.filter(item=>item.group_id==='enterprise_capability_basis'||item.group_id==='enterprise_capability_gaps'))
const proposalGroups=computed(()=>props.payload.proposed_solution.capability_groups.filter(item=>item.group_id!=='enterprise_capability_basis'&&item.group_id!=='enterprise_capability_gaps'))
const activeSources=computed(()=>{
  const ids=activeClaim.value?props.claimSources[activeClaim.value]??[]:[]
  return [...new Set(ids)].map(id=>sourceMap.value.get(id)).filter((item):item is SafeSolutionSource=>!!item)
})
const activeClaimText=computed(()=>activeClaim.value?claims.value.get(activeClaim.value)?.text??'':'')
const claim=(id:string):V2Claim|undefined=>claims.value.get(id)
const sourceCount=(id:string)=>new Set((props.claimSources[id]??[]).filter(sourceId=>sourceMap.value.has(sourceId))).size
const hasSources=(id:string)=>sourceCount(id)>0
const componentName=(id:string)=>componentNames.value.get(id)??'未识别组件'
const phaseName=(id:string)=>phaseNames.value.get(id)??'未识别阶段'
const acceptanceText=(id:string)=>{
  const claimId=acceptanceClaims.value.get(id)
  return claimId?claim(claimId)?.text??'验收条件不可用':'验收条件不可用'
}
const requirementLabels=(id:string)=>[...new Set(claim(id)?.related_requirement_fields??[])].map(label)
const typeLabel:Record<V2Claim['statement_type'],string>={customer_fact:'客户事实',enterprise_fact:'企业事实',proposal:'方案建议',assumption:'假设',unresolved:'待确认'}
</script>

<template>
  <nav class="solution-section-nav" data-test="solution-section-nav" aria-label="方案章节">
    <a v-for="item in [['summary','执行摘要'],['proposal','总体方案'],['architecture','系统架构'],['deployment','部署与集成'],['implementation','实施计划'],['risks','风险'],['acceptance','验收标准'],['milestones','里程碑'],['assumptions','假设'],['questions','待确认事项'],['customer','客户背景'],['scope','范围边界']]" :key="item[0]" :href="`#v2-${item[0]}`">{{item[1]}}</a>
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

  <section id="v2-summary" class="panel solution-section solution-summary-section">
    <div class="section-heading"><div><p class="section-kicker">先看结论</p><h2>执行摘要</h2></div></div>
    <ul class="claim-list summary-claims"><li v-for="id in payload.executive_summary" :key="id"><el-tag size="small">{{claim(id)?typeLabel[claim(id)!.statement_type]:''}}</el-tag><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看 {{sourceCount(id)}} 条来源</button></li></ul>
  </section>

  <section id="v2-proposal" class="panel solution-section">
    <p class="section-kicker">WHAT WE RECOMMEND</p><h2>总体方案</h2>
    <div class="recommendation-block"><h3>核心推荐</h3><div v-for="id in payload.proposed_solution.overview_claim_ids" :key="id" class="claim-row"><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看 {{sourceCount(id)}} 条来源</button></div></div>
    <article v-for="group in proposalGroups" :key="group.group_id" class="proposal-consideration" data-test="proposal-consideration"><p class="field-label">方案取舍 / 补充</p><h3>{{group.title}}</h3><div v-for="id in group.claim_ids" :key="id" class="claim-row"><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看 {{sourceCount(id)}} 条来源</button></div></article>
    <details v-for="group in capabilityBasis" :key="group.group_id" class="capability-basis" data-test="enterprise-capability-basis"><summary>{{group.title}} <span>（{{group.claim_ids.length}} 项）</span></summary><p class="muted">这些事实说明企业已有能力或仍需确认的能力边界，不等同于本方案的技术建议。</p><div v-for="id in group.claim_ids" :key="id" class="claim-row"><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看 {{sourceCount(id)}} 条来源</button></div></details>
  </section>

  <section id="v2-architecture" class="panel solution-section">
    <p class="section-kicker">SYSTEM DESIGN</p><h2>系统架构</h2>
    <div class="section-intro" v-for="id in payload.architecture.overview_claim_ids" :key="id"><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看 {{sourceCount(id)}} 条来源</button></div>
    <div class="architecture-grid narrow-stack-grid">
      <article v-for="(component,index) in payload.architecture.components" :key="component.component_id" class="architecture-component" data-test="architecture-component">
        <header><span class="step-index">{{index+1}}</span><h3>{{componentTitle(component)}}</h3></header>
        <div v-if="component.responsibility_claim_ids.length" class="structured-field"><h4>职责</h4><div v-for="id in component.responsibility_claim_ids" :key="id" class="claim-row"><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看来源</button></div></div>
        <div v-if="component.rationale_claim_ids.length" class="structured-field rationale-field"><h4>推荐理由</h4><div v-for="id in component.rationale_claim_ids" :key="id" class="claim-row"><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看来源</button></div></div>
        <div v-if="component.interface_claim_ids.length" class="structured-field"><h4>接口 / 交互</h4><div v-for="id in component.interface_claim_ids" :key="id" class="claim-row"><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看来源</button></div></div>
        <div v-if="component.dependency_component_ids.length" class="relation-row"><strong>前置依赖</strong><span v-for="id in component.dependency_component_ids" :key="id" class="relation-chip">{{componentName(id)}}</span></div>
      </article>
    </div>
    <div class="architecture-flow-grid narrow-stack-grid">
      <section v-if="requestFlows.length" class="flow-panel" data-test="architecture-request-flow">
        <p class="field-label">REQUEST FLOW</p><h3>主要请求流</h3>
        <div v-for="(flow,index) in requestFlows" :key="`request-${flow.source_component_id}-${flow.target_component_id}-${index}`" class="flow-edge">
          <span class="flow-node">{{componentName(flow.source_component_id)}}</span><span class="flow-arrow" aria-hidden="true">→</span><span class="flow-node">{{componentName(flow.target_component_id)}}</span>
        </div>
      </section>
      <section v-if="dataFlows.length" class="flow-panel" data-test="architecture-data-flow">
        <p class="field-label">DATA FLOW</p><h3>数据流</h3>
        <div v-for="(flow,index) in dataFlows" :key="`data-${flow.source_component_id}-${flow.target_component_id}-${index}`" class="flow-edge">
          <span class="flow-node">{{componentName(flow.source_component_id)}}</span><span class="flow-arrow" aria-hidden="true">→</span><span class="flow-node">{{componentName(flow.target_component_id)}}</span>
        </div>
      </section>
    </div>
  </section>

  <section id="v2-deployment" class="panel solution-section">
    <p class="section-kicker">DELIVERY BOUNDARY</p><h2>部署与集成</h2>
    <div class="topic-grid"><article v-for="block in payload.deployment_and_integration" :key="block.block_id" class="topic-card"><h3>{{block.title}}</h3><div v-for="id in block.claim_ids" :key="id" class="claim-row"><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看 {{sourceCount(id)}} 条来源</button></div></article></div>
  </section>

  <section id="v2-implementation" class="panel solution-section">
    <p class="section-kicker">DELIVERY PLAN</p><h2>实施计划</h2>
    <div class="phase-timeline">
      <article v-for="(phase,index) in payload.implementation_plan.phases" :key="phase.phase_id" class="phase-card" data-test="implementation-phase">
        <header><span class="phase-number">{{index+1}}</span><div><p>实施步骤 {{index+1}}</p><h3>{{phase.name}}</h3></div></header>
        <div v-if="phase.objective_claim_ids.length" class="structured-field"><h4>阶段目标</h4><div v-for="id in phase.objective_claim_ids" :key="id" class="claim-row"><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看来源</button></div></div>
        <div v-if="phase.task_claim_ids.length" class="structured-field"><h4>主要任务</h4><ul><li v-for="id in phase.task_claim_ids" :key="id"><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看来源</button></li></ul></div>
        <div v-if="phase.deliverable_claim_ids.length" class="structured-field deliverable-field"><h4>交付物</h4><div v-for="id in phase.deliverable_claim_ids" :key="id" class="claim-row"><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看来源</button></div></div>
        <div v-if="phase.dependency_phase_ids.length" class="relation-row"><strong>前置阶段</strong><span v-for="id in phase.dependency_phase_ids" :key="id" class="relation-chip">{{phaseName(id)}}</span></div>
        <div v-if="phase.acceptance_criterion_ids.length" class="structured-field exit-field"><h4>验收 / 退出条件</h4><p v-for="id in phase.acceptance_criterion_ids" :key="id">{{acceptanceText(id)}}</p></div>
        <div v-if="phase.timing_claim_id" class="structured-field"><h4>时间边界</h4><p>{{claim(phase.timing_claim_id)?.text}}</p></div>
      </article>
    </div>
  </section>

  <section id="v2-risks" class="panel solution-section">
    <p class="section-kicker">TECHNICAL RISKS</p><h2>技术风险</h2><p class="muted">风险是在方案成立后仍可能发生的问题；信息缺失单独列在“待确认事项”。</p>
    <div class="risk-grid"><article v-for="(risk,index) in payload.risks" :key="risk.risk_id" class="risk-card" data-test="risk-card"><header><span>风险 {{index+1}}</span></header><div class="structured-field risk-condition"><h4>风险条件</h4><div class="claim-row"><span>{{claim(risk.condition_claim_id)?.text}}</span><button v-if="hasSources(risk.condition_claim_id)" :data-test="`sources-${risk.condition_claim_id}`" class="source-link" @click="activeClaim=risk.condition_claim_id">查看来源</button></div></div><div v-if="risk.impact_claim_ids.length" class="structured-field"><h4>可能影响</h4><div v-for="id in risk.impact_claim_ids" :key="id" class="claim-row"><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看来源</button></div></div><div v-if="risk.mitigation_claim_ids.length" class="structured-field mitigation-field"><h4>缓解措施</h4><div v-for="id in risk.mitigation_claim_ids" :key="id" class="claim-row"><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看来源</button></div></div><div v-if="risk.trigger_claim_ids.length" class="structured-field"><h4>触发 / 观察信号</h4><div v-for="id in risk.trigger_claim_ids" :key="id" class="claim-row"><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看来源</button></div></div></article></div>
  </section>

  <section id="v2-acceptance" class="panel solution-section">
    <p class="section-kicker">VERIFICATION</p><h2>验收标准</h2>
    <div class="acceptance-list"><article v-for="(item,index) in payload.acceptance_criteria" :key="item.criterion_id" class="acceptance-card" data-test="acceptance-criterion"><span class="acceptance-index">{{index+1}}</span><div><h3>如何验证</h3><p>{{claim(item.claim_id)?.text}}</p><div v-if="requirementLabels(item.claim_id).length" class="requirement-links"><span>对应需求</span><el-tag v-for="itemLabel in requirementLabels(item.claim_id)" :key="itemLabel" size="small" effect="plain">{{itemLabel}}</el-tag></div><button v-if="hasSources(item.claim_id)" :data-test="`sources-${item.claim_id}`" class="source-link" @click="activeClaim=item.claim_id">查看 {{sourceCount(item.claim_id)}} 条来源</button></div></article></div>
  </section>

  <section id="v2-milestones" class="panel solution-section">
    <p class="section-kicker">DELIVERY CHECKPOINTS</p><h2>里程碑</h2>
    <div class="milestone-list"><article v-for="item in payload.milestones" :key="item.milestone_id" class="milestone-card" data-test="milestone-card"><h3>{{item.name}}</h3><div v-if="item.related_phase_ids.length" class="relation-row"><strong>对应阶段</strong><span v-for="id in item.related_phase_ids" :key="id" class="relation-chip">{{phaseName(id)}}</span></div><div v-for="id in item.outcome_claim_ids" :key="id" class="claim-row"><span>{{claim(id)?.text}}</span><button v-if="hasSources(id)" :data-test="`sources-${id}`" class="source-link" @click="activeClaim=id">查看来源</button></div><p v-if="item.timing_claim_id" class="muted">时间边界：{{claim(item.timing_claim_id)?.text}}</p></article></div>
  </section>

  <section id="v2-assumptions" class="panel solution-section compact-section"><h2>假设</h2><p v-if="!payload.assumptions.length" class="muted">当前没有显式方案假设。</p><p v-for="id in payload.assumptions" :key="id">{{claim(id)?.text}}</p></section>
  <section id="v2-questions" class="panel solution-section open-question-section"><h2>待确认事项</h2><p class="muted">以下信息尚未确认，不会被当作客户事实或技术承诺。</p><article v-for="item in payload.open_questions" :key="item.question_id"><el-tag type="warning" effect="light">{{label(item.requirement_field)}}</el-tag><span>{{claim(item.unresolved_claim_id)?.text}}</span></article></section>
  <section id="v2-customer" class="panel solution-section customer-context-section"><p class="section-kicker">CONFIRMED CONTEXT</p><h2>客户背景</h2><p class="muted">这里集中展示已确认需求和仍待确认的背景，不等同于方案建议。</p><ul class="claim-list"><li v-for="id in [...payload.customer_context.confirmed_claim_ids,...payload.customer_context.unresolved_claim_ids]" :key="id"><el-tag size="small">{{claim(id)?typeLabel[claim(id)!.statement_type]:''}}</el-tag><span>{{claim(id)?.text}}</span></li></ul></section>
  <section id="v2-scope" class="panel solution-section compact-section"><h2>范围边界</h2><div v-for="item in payload.out_of_scope" :key="item.scope_id" class="claim-row"><span>{{claim(item.claim_id)?.text}}</span><button v-if="hasSources(item.claim_id)" :data-test="`sources-${item.claim_id}`" class="source-link" @click="activeClaim=item.claim_id">查看 {{sourceCount(item.claim_id)}} 条来源</button></div></section>
  <SolutionSourceDrawer :open="activeClaim!==null" :claim-text="activeClaimText" :sources="activeSources" @close="activeClaim=null" />
</template>

<style scoped>
.solution-section-nav{position:sticky;top:0;z-index:5;display:flex;max-width:100%;min-width:0;gap:8px;overflow-x:auto;margin:18px 0;padding:12px;background:rgba(255,255,255,.96);border:1px solid #e1e6ef;border-radius:10px;box-shadow:0 6px 18px rgba(31,45,71,.06)}.solution-section-nav a{white-space:nowrap;color:#365b95;text-decoration:none;padding:4px 6px}.solution-section{min-width:0;max-width:100%;scroll-margin-top:72px}.section-kicker,.field-label{margin:0 0 6px;color:#6b7f9b;font-size:11px;font-weight:750;letter-spacing:1.4px}.section-heading{display:flex;justify-content:space-between}.section-intro{padding:15px 18px;margin-bottom:18px;border-left:3px solid #6f91c5;background:#f5f8fc;line-height:1.7}.review-focus{border-color:#cfdcf0;background:linear-gradient(135deg,#fff,#f5f8fd)}.review-focus-heading{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}.review-focus-heading h2{margin-top:4px}.review-focus-counts{display:flex;gap:8px;flex-wrap:wrap}.review-focus-counts span{padding:5px 9px;border-radius:999px;background:#e8f0fc;color:#315f9d;font-size:12px;font-weight:600}.review-focus-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.review-focus-grid article{padding:16px;border:1px solid #dde5f0;border-radius:9px;background:#fff}.review-focus-grid h3{margin-top:0}.review-focus-grid a{display:block;margin-top:10px;line-height:1.55;color:#314a6c}.claim-list{display:grid;gap:14px;padding:0;list-style:none}.claim-list li,.claim-row{display:flex;min-width:0;align-items:flex-start;gap:10px;line-height:1.7}.claim-row>span{min-width:0;overflow-wrap:anywhere}.summary-claims{font-size:15px}.source-link{margin-left:auto;border:0;background:none;color:#315f9d;cursor:pointer;white-space:nowrap;font-size:13px}.source-link:hover{text-decoration:underline}.recommendation-block{padding:20px;border:1px solid #cddbf0;border-radius:10px;background:#f6f9fd}.recommendation-block h3{margin-top:0;color:#234d86}.proposal-consideration{margin-top:16px;padding:18px;border-left:3px solid #d09b39;background:#fff9ec}.proposal-consideration h3{margin:4px 0 12px}.capability-basis{margin-top:20px;background:#f7f9fc;border-color:#e5eaf1}.capability-basis summary{font-weight:650}.capability-basis summary span{font-weight:400;color:#718096}.architecture-grid,.topic-grid,.risk-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.narrow-stack-grid,.architecture-component,.flow-panel{min-width:0;max-width:100%}.architecture-component,.topic-card,.risk-card,.milestone-card{padding:20px;border:1px solid #dfe6ef;border-radius:10px;background:#fff}.architecture-component header,.phase-card header{display:flex;align-items:center;gap:12px;border-bottom:1px solid #e9edf3;padding-bottom:12px;margin-bottom:14px}.architecture-component h3,.phase-card h3{min-width:0;margin:0;overflow-wrap:anywhere}.step-index,.phase-number,.acceptance-index{display:grid;place-items:center;flex:0 0 30px;height:30px;border-radius:50%;background:#315f9d;color:white;font-weight:700}.structured-field{min-width:0;padding:10px 0}.structured-field h4{margin:0 0 7px;color:#52657d;font-size:12px;letter-spacing:.4px}.rationale-field{border-left:3px solid #8fb2e3;padding-left:12px;background:#f7faff}.deliverable-field,.mitigation-field,.exit-field{border-left:3px solid #65a17c;padding-left:12px;background:#f6fbf8}.relation-row{display:flex;min-width:0;align-items:center;gap:7px;flex-wrap:wrap;margin-top:12px;color:#52657d;font-size:13px}.relation-chip{max-width:100%;padding:4px 8px;border-radius:999px;background:#edf2f8;color:#405570;overflow-wrap:anywhere}.architecture-flow-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-top:20px}.flow-panel{padding:18px;border:1px solid #d8e2f0;border-radius:10px;background:#f8fafd}.flow-panel h3{margin:0 0 14px;color:#284f84}.flow-edge{display:grid;min-width:0;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:center;gap:10px;padding:10px 0;border-top:1px solid #e3e9f2}.flow-node{min-width:0;padding:7px 9px;border-radius:7px;background:#fff;border:1px solid #dfe6ef;color:#344b69;text-align:center;overflow-wrap:anywhere}.flow-arrow{color:#315f9d;font-size:20px;font-weight:700}.phase-timeline{display:grid;gap:18px}.phase-card{position:relative;padding:22px 22px 22px 28px;border:1px solid #dfe6ef;border-left:4px solid #5e83bb;border-radius:10px;background:#fff}.phase-card header p{margin:0;color:#72839b;font-size:11px;text-transform:uppercase;letter-spacing:1px}.phase-card ul{margin:0;padding-left:20px}.risk-card header{margin:-20px -20px 14px;padding:10px 16px;background:#fff5ea;border-bottom:1px solid #f2dfc9;border-radius:10px 10px 0 0;color:#8b5d21;font-weight:700}.risk-condition{font-weight:620}.acceptance-list,.milestone-list{display:grid;gap:14px}.acceptance-card{display:flex;gap:14px;padding:18px;border:1px solid #dfe6ef;border-radius:10px;background:#fff}.acceptance-card h3{margin:0 0 6px}.acceptance-card p{margin:0 0 10px}.requirement-links{display:flex;align-items:center;gap:6px;flex-wrap:wrap;color:#64748b;font-size:12px}.open-question-section{border-left:4px solid #d09b39}.open-question-section article{display:flex;align-items:flex-start;gap:10px;padding:12px 0;border-top:1px solid #edf0f4}.customer-context-section,.compact-section{background:#fafbfd}.customer-context-section{border-color:#e7ebf1}.muted{color:#64748b}@media(max-width:900px){.review-focus-heading{display:block}.review-focus-grid,.narrow-stack-grid,.topic-grid,.risk-grid{grid-template-columns:minmax(0,1fr)}.solution-section-nav{top:0}}@media(max-width:600px){.architecture-component,.topic-card,.risk-card,.phase-card,.acceptance-card,.milestone-card{padding:16px}.risk-card header{margin:-16px -16px 12px}.source-link{margin-left:0}.claim-row{flex-wrap:wrap}.flow-edge{grid-template-columns:1fr}.flow-arrow{text-align:center;transform:rotate(90deg)}}
</style>
