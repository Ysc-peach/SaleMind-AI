export const labels: Record<string, string> = {
  admin: '业务管理员', sales: '销售', presales: '售前', initial_contact: '初步接触', requirement_analysis: '需求分析', presales_support: '售前支持', solution: '方案制定', quotation: '报价', negotiation: '商务谈判', active: '进行中', won: '已赢单', lost: '已丢单', closed: '已关闭',
  known: '已确认', unknown: '信息缺失', unclear: '尚不明确', conflict: '信息冲突',
  draft: '草稿', pending_review: '等待售前审核', approved: '技术审核已通过', needs_revision: '需要处理退回意见', pending: '审核中', returned: '已退回',
  customer_info_required: '需要补充客户信息', technical_revision_required: '需要修改技术方案',
  newer_requirement_analysis: '存在更新的需求分析', grounding_fact_invalid: '企业事实已失效', grounding_provenance_invalid: '证据来源已失效',
  customer_fact: '客户事实', enterprise_fact: '企业事实', proposal: '方案建议', unresolved: '待确认',
  business_goal: '业务目标', use_scenario: '使用场景', user_scale: '用户规模', deployment_requirement: '部署要求', data_security_requirement: '数据安全', existing_environment: '现有环境', integration_requirement: '系统集成', timeline: '时间计划', budget: '预算', technical_constraints: '技术约束',
}
export const label = (value: string) => labels[value] ?? '未知状态'
export function dateTime(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN') }
