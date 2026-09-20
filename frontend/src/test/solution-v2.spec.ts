import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import SolutionV2Renderer from '../components/solution/SolutionV2Renderer.vue'
import type { V2ClaimType, V2Payload } from '../types/workflow'

const claim = (claim_id:string, statement_type:V2ClaimType, text:string, citations:string[]=[], related_requirement_fields:string[]=[]) => ({
  claim_id, statement_type, text, citations, related_requirement_fields,
})

const payload:V2Payload = {
  title:'企业知识查询技术方案',
  claims:[
    claim('C0001','customer_fact','客户需要企业知识查询。'),
    claim('C0002','enterprise_fact','系统支持私有化部署。',['S1']),
    claim('C0003','proposal','建议采用知识服务组件。',['S1']),
    claim('C0004','assumption','上线窗口需要客户确认。'),
    claim('C0005','unresolved','具体上线日期待确认。'),
    claim('C0006','proposal','建议验证可用性目标。',['S2'],['technical_constraints']),
    claim('C0007','proposal','企业入口负责接收顾问查询。',['S1'],['use_scenario']),
    claim('C0008','proposal','检索前过滤可避免跨项目资料进入上下文。',['S1'],['data_security_requirement']),
    claim('C0009','proposal','身份组件向知识服务传递项目访问范围。',['S1'],['integration_requirement']),
    claim('C0010','proposal','确认身份与资料权限边界。',['S1'],['integration_requirement']),
    claim('C0011','proposal','梳理身份字段和资料访问角色。',['S1'],['integration_requirement']),
    claim('C0012','proposal','交付经确认的权限与接口清单。',['S1'],['integration_requirement']),
    claim('C0013','proposal','若权限映射不一致，受限资料可能进入错误范围。',['S1'],['data_security_requirement']),
    claim('C0014','proposal','可能造成内部资料越权暴露。',['S1'],['data_security_requirement']),
    claim('C0015','proposal','在摄取和查询阶段分别执行权限校验。',['S1'],['data_security_requirement']),
    claim('C0016','proposal','权限抽样发现越权结果时触发整改。',['S1'],['data_security_requirement']),
    claim('C0017','proposal','身份与权限边界完成验收。',['S2'],['integration_requirement']),
    claim('C0018','proposal','检索规模显著变化时应重新评估独立向量检索能力。',['S1'],['technical_constraints']),
    claim('C0019','proposal','统一身份与权限服务',['S1'],['data_security_requirement']),
    claim('C0020','proposal','知识检索编排服务',['S1'],['use_scenario']),
    claim('C0021','proposal','独立检索编排可隔离入口与知识存储边界。',['S1'],['use_scenario']),
    claim('C0022','proposal','检索编排服务向身份服务校验访问范围并读取知识数据。',['S1'],['integration_requirement']),
  ],
  executive_summary:['C0001','C0003'],
  customer_context:{confirmed_claim_ids:['C0001'],unresolved_claim_ids:['C0005'],requirement_fields:[]},
  proposed_solution:{overview_claim_ids:['C0003'],capability_groups:[
    {group_id:'enterprise_capability_basis',title:'企业能力依据',claim_ids:['C0002']},
    {group_id:'tradeoff_group',title:'方案分组 1',claim_ids:['C0018']},
  ]},
  architecture:{overview_claim_ids:['C0003'],components:[
    {component_id:'identity_boundary',name:'架构组件 1',identity_claim_id:'C0019',responsibility_claim_ids:['C0007'],rationale_claim_ids:['C0008'],dependency_component_ids:[],interface_claim_ids:['C0009']},
    {component_id:'knowledge_service',name:'架构组件 2',identity_claim_id:'C0020',responsibility_claim_ids:['C0003'],rationale_claim_ids:['C0021'],dependency_component_ids:['identity_boundary'],interface_claim_ids:['C0022']},
  ],flows:[
    {flow_type:'request',source_component_id:'identity_boundary',target_component_id:'knowledge_service'},
    {flow_type:'data',source_component_id:'knowledge_service',target_component_id:'identity_boundary'},
  ]},
  deployment_and_integration:[{block_id:'deployment',topic:'deployment',title:'部署',claim_ids:['C0002']}],
  implementation_plan:{phases:[
    {phase_id:'discovery',name:'实施阶段 1',objective_claim_ids:['C0010'],task_claim_ids:['C0011'],owner_roles:['tbd'],deliverable_claim_ids:['C0012'],dependency_phase_ids:[],acceptance_criterion_ids:[],timing_claim_id:null,timing_classification:null},
    {phase_id:'delivery',name:'实施阶段 2',objective_claim_ids:['C0003'],task_claim_ids:['C0011'],owner_roles:['tbd'],deliverable_claim_ids:['C0012'],dependency_phase_ids:['discovery'],acceptance_criterion_ids:['acceptance'],timing_claim_id:'C0005',timing_classification:'unresolved'},
  ]},
  risks:[{risk_id:'permission_leakage',condition_claim_id:'C0013',impact_claim_ids:['C0014'],mitigation_claim_ids:['C0015'],trigger_claim_ids:['C0016']}],
  acceptance_criteria:[{criterion_id:'acceptance',claim_id:'C0006',classification:'proposed'}],
  milestones:[{milestone_id:'scope_internal_id',name:'里程碑 1',related_phase_ids:['delivery'],outcome_claim_ids:['C0017'],timing_claim_id:'C0005',timing_classification:'unresolved'}],
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

it('renders architecture responsibilities, rationale, interfaces, and named dependencies',()=>{
  const wrapper=mount(SolutionV2Renderer,{props:{payload,sourceRegistry:[],claimSources:{}},global:{plugins:[ElementPlus]}})

  const components=wrapper.findAll('[data-test="architecture-component"]')
  expect(components).toHaveLength(2)
  expect(components[0].text()).toContain('职责')
  expect(components[0].text()).toContain('企业入口负责接收顾问查询。')
  expect(components[0].text()).toContain('推荐理由')
  expect(components[0].text()).toContain('检索前过滤可避免跨项目资料进入上下文。')
  expect(components[0].text()).toContain('接口 / 交互')
  expect(components[0].text()).toContain('统一身份与权限服务')
  expect(components[0].text()).not.toContain('架构组件 1')
  expect(components[1].text()).toContain('知识检索编排服务')
  expect(components[1].text()).toContain('前置依赖')
  expect(components[1].text()).toContain('统一身份与权限服务')
  expect(wrapper.text()).not.toContain('identity_boundary')
  expect(wrapper.text()).not.toContain('C0019')
})

it('renders request and data flows separately from dependencies using semantic names',()=>{
  const wrapper=mount(SolutionV2Renderer,{props:{payload,sourceRegistry:[],claimSources:{}},global:{plugins:[ElementPlus]}})

  expect(wrapper.get('.architecture-grid').classes()).toContain('narrow-stack-grid')
  expect(wrapper.get('.architecture-flow-grid').classes()).toContain('narrow-stack-grid')
  const requestFlow=wrapper.get('[data-test="architecture-request-flow"]')
  expect(requestFlow.text()).toContain('主要请求流')
  expect(requestFlow.text()).toContain('统一身份与权限服务')
  expect(requestFlow.text()).toContain('知识检索编排服务')
  const dataFlow=wrapper.get('[data-test="architecture-data-flow"]')
  expect(dataFlow.text()).toContain('数据流')
  expect(dataFlow.text()).toContain('知识检索编排服务')
  expect(dataFlow.text()).toContain('统一身份与权限服务')
  expect(wrapper.text()).not.toContain('identity_boundary')
  expect(wrapper.text()).not.toContain('knowledge_service')
})

it('uses the neutral name only as a safe fallback for historical V2 payloads',()=>{
  const historical:V2Payload={
    ...payload,
    architecture:{
      ...payload.architecture,
      components:payload.architecture.components.map(({identity_claim_id:_identity,...component})=>component),
    },
  }
  const wrapper=mount(SolutionV2Renderer,{props:{payload:historical,sourceRegistry:[],claimSources:{}},global:{plugins:[ElementPlus]}})

  expect(wrapper.findAll('[data-test="architecture-component"]')[0].text()).toContain('架构组件 1')
})

it('does not silently use the historical fallback for a dangling identity reference',()=>{
  const invalid:V2Payload={
    ...payload,
    architecture:{
      ...payload.architecture,
      components:payload.architecture.components.map((component,index)=>index===0?{...component,identity_claim_id:'C9999'}:component),
    },
  }
  const wrapper=mount(SolutionV2Renderer,{props:{payload:invalid,sourceRegistry:[],claimSources:{}},global:{plugins:[ElementPlus]}})

  expect(wrapper.findAll('[data-test="architecture-component"]')[0].text()).toContain('组件名称不可用')
  expect(wrapper.findAll('[data-test="architecture-component"]')[0].text()).not.toContain('架构组件 1')
})

it('separates core recommendations, rationale, and proposal tradeoff considerations',()=>{
  const wrapper=mount(SolutionV2Renderer,{props:{payload,sourceRegistry:[],claimSources:{}},global:{plugins:[ElementPlus]}})

  expect(wrapper.get('.recommendation-block').text()).toContain('核心推荐')
  expect(wrapper.get('.rationale-field').text()).toContain('推荐理由')
  const consideration=wrapper.get('[data-test="proposal-consideration"]')
  expect(consideration.text()).toContain('方案取舍 / 补充')
  expect(consideration.text()).toContain('检索规模显著变化时应重新评估独立向量检索能力。')
})

it('renders implementation phases as a delivery chain with dependencies and exit criteria',()=>{
  const wrapper=mount(SolutionV2Renderer,{props:{payload,sourceRegistry:[],claimSources:{}},global:{plugins:[ElementPlus]}})

  const phases=wrapper.findAll('[data-test="implementation-phase"]')
  expect(phases).toHaveLength(2)
  expect(phases[0].text()).toContain('阶段目标')
  expect(phases[0].text()).toContain('主要任务')
  expect(phases[0].text()).toContain('交付物')
  expect(phases[1].text()).toContain('前置阶段')
  expect(phases[1].text()).toContain('实施阶段 1')
  expect(phases[1].text()).toContain('验收 / 退出条件')
  expect(phases[1].text()).toContain('建议验证可用性目标。')
  expect(wrapper.text()).not.toContain('discovery')
})

it('renders risks, acceptance linkage, and milestone phase relations with safe labels',()=>{
  const wrapper=mount(SolutionV2Renderer,{props:{payload,sourceRegistry:[],claimSources:{}},global:{plugins:[ElementPlus]}})

  const risk=wrapper.get('[data-test="risk-card"]')
  expect(risk.text()).toContain('风险条件')
  expect(risk.text()).toContain('可能影响')
  expect(risk.text()).toContain('缓解措施')
  expect(risk.text()).toContain('触发 / 观察信号')
  const acceptance=wrapper.get('[data-test="acceptance-criterion"]')
  expect(acceptance.text()).toContain('如何验证')
  expect(acceptance.text()).toContain('技术约束')
  expect(acceptance.text()).not.toContain('technical_constraints')
  const milestone=wrapper.get('[data-test="milestone-card"]')
  expect(milestone.text()).toContain('对应阶段')
  expect(milestone.text()).toContain('实施阶段 2')
  expect(wrapper.text()).not.toContain('scope_internal_id')
})

it('keeps enterprise capability evidence in a secondary collapsed section',()=>{
  const wrapper=mount(SolutionV2Renderer,{props:{payload,sourceRegistry:[],claimSources:{}},global:{plugins:[ElementPlus]}})

  const basis=wrapper.get('[data-test="enterprise-capability-basis"]')
  expect(basis.element.tagName).toBe('DETAILS')
  expect(basis.attributes('open')).toBeUndefined()
  expect(basis.get('summary').text()).toContain('企业能力依据')
})

it('provides long-page navigation and a reviewer focus summary',()=>{
  const wrapper=mount(SolutionV2Renderer,{props:{
    payload,
    sourceRegistry:[
      {source_id:'S1',document_id:5,document_title:'产品能力说明',source_excerpt:'支持私有化部署。'},
      {source_id:'S2',document_id:6,document_title:'验收说明',source_excerpt:'验收指标需要协商。'},
    ],
    claimSources:{C0002:['S1'],C0003:['S1'],C0006:['S2']},
  },global:{plugins:[ElementPlus]}})

  const nav=wrapper.get('[data-test="solution-section-nav"]')
  for(const target of ['summary','customer','proposal','architecture','deployment','implementation','risks','acceptance','milestones','assumptions','questions','scope']){
    expect(nav.find(`a[href="#v2-${target}"]`).exists()).toBe(true)
  }
  const focus=wrapper.get('[data-test="review-focus"]')
  expect(focus.text()).toContain('审核重点')
  expect(focus.text()).toContain('具体上线日期待确认。')
  expect(focus.text()).toContain('建议验证可用性目标。')
  expect(focus.text()).toContain('1 项风险')
  expect(focus.text()).toContain('1 项待确认')
  expect(focus.text()).toContain('1 项验收条件')
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

it('deduplicates a claim source, keeps claim context, and hides internal source ids',async()=>{
  const wrapper=mount(SolutionV2Renderer,{props:{
    payload,
    sourceRegistry:[
      {source_id:'S1',document_id:5,document_title:'产品能力说明',source_excerpt:'支持私有化部署。'},
      {source_id:'S1',document_id:5,document_title:'产品能力说明',source_excerpt:'支持私有化部署。'},
    ],
    claimSources:{C0003:['S1','S1']},
  },global:{plugins:[ElementPlus]}})

  expect(wrapper.get('[data-test="sources-C0003"]').text()).toContain('1 条来源')
  await wrapper.get('[data-test="sources-C0003"]').trigger('click')
  const drawer=wrapper.get('[data-test="source-drawer"]')
  expect(drawer.text()).toContain('建议采用知识服务组件。')
  expect(drawer.findAll('[data-test="source-card"]')).toHaveLength(1)
  expect(drawer.text()).not.toContain('S1')
})
