import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import SolutionV2Renderer from '../components/solution/SolutionV2Renderer.vue'
import type { V2ClaimType, V2Payload } from '../types/workflow'

const claim = (claim_id:string, statement_type:V2ClaimType, text:string, citations:string[]=[]) => ({
  claim_id, statement_type, text, citations, related_requirement_fields:[],
})

const payload:V2Payload = {
  title:'企业知识查询技术方案',
  claims:[
    claim('C0001','customer_fact','客户需要企业知识查询。'),
    claim('C0002','enterprise_fact','系统支持私有化部署。',['S1']),
    claim('C0003','proposal','建议采用知识服务组件。',['S1']),
    claim('C0004','assumption','上线窗口需要客户确认。'),
    claim('C0005','unresolved','具体上线日期待确认。'),
    claim('C0006','proposal','建议验证可用性目标。',['S2']),
  ],
  executive_summary:['C0001','C0003'],
  customer_context:{confirmed_claim_ids:['C0001'],unresolved_claim_ids:['C0005'],requirement_fields:[]},
  proposed_solution:{overview_claim_ids:['C0002','C0003'],capability_groups:[]},
  architecture:{overview_claim_ids:['C0003'],components:[{component_id:'knowledge_service',name:'知识服务',responsibility_claim_ids:['C0003'],rationale_claim_ids:['C0002'],dependency_component_ids:[],interface_claim_ids:[]}]},
  deployment_and_integration:[{block_id:'deployment',topic:'deployment',title:'部署',claim_ids:['C0002']}],
  implementation_plan:{phases:[{phase_id:'delivery',name:'交付',objective_claim_ids:['C0003'],task_claim_ids:['C0003'],owner_roles:['tbd'],deliverable_claim_ids:['C0003'],dependency_phase_ids:[],acceptance_criterion_ids:['acceptance'],timing_claim_id:'C0005',timing_classification:'unresolved'}]},
  risks:[{risk_id:'availability',condition_claim_id:'C0005',impact_claim_ids:[],mitigation_claim_ids:['C0006'],trigger_claim_ids:[]}],
  acceptance_criteria:[{criterion_id:'acceptance',claim_id:'C0006',classification:'proposed'}],
  milestones:[{milestone_id:'scope',name:'范围确认',related_phase_ids:['delivery'],outcome_claim_ids:['C0003'],timing_claim_id:'C0005',timing_classification:'unresolved'}],
  assumptions:['C0004'],
  open_questions:[{question_id:'timeline',requirement_field:'timeline',requirement_status:'unknown',unresolved_claim_id:'C0005'}],
  out_of_scope:[{scope_id:'scope_item',claim_id:'C0005',classification:'unresolved'}],
}

it('renders the structured V2 sections through claim references instead of a JSON dump',()=>{
  const wrapper=mount(SolutionV2Renderer,{props:{
    payload,
    sourceRegistry:[],
    claimSources:{},
  },global:{plugins:[ElementPlus]}})

  for(const heading of ['执行摘要','客户背景','总体方案','系统架构','部署与集成','实施计划','风险','验收标准','里程碑','假设','待确认事项','范围边界']){
    expect(wrapper.text()).toContain(heading)
  }
  expect(wrapper.text()).toContain('建议采用知识服务组件。')
  expect(wrapper.text()).not.toContain('"claim_id"')
})

it('opens only sources mapped to the selected claim and omits audit internals',async()=>{
  const wrapper=mount(SolutionV2Renderer,{props:{
    payload,
    sourceRegistry:[
      {source_id:'S1',document_id:5,document_title:'产品能力说明',source_excerpt:'支持私有化部署。'},
      {source_id:'S2',document_id:6,document_title:'验收说明',source_excerpt:'验收指标需要协商。'},
    ],
    claimSources:{C0002:['S1'],C0003:['S1'],C0006:['S2']},
  },global:{plugins:[ElementPlus]}})

  await wrapper.get('[data-test="sources-C0003"]').trigger('click')
  expect(wrapper.text()).toContain('产品能力说明')
  expect(wrapper.text()).toContain('支持私有化部署。')
  expect(wrapper.text()).not.toContain('验收指标需要协商。')
  await wrapper.get('aside button').trigger('click')
  await wrapper.get('[data-test="sources-C0006"]').trigger('click')
  expect(wrapper.text()).toContain('验收指标需要协商。')
  expect(wrapper.text()).not.toContain('产品能力说明')
  for(const forbidden of ['content hash','index run','grounding ID','provider raw']){
    expect(wrapper.text()).not.toContain(forbidden)
  }
})
