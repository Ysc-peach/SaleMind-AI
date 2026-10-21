const messages: Record<number, string> = {
  400: '输入不符合要求，请检查所填字段。', 401: '登录已失效，请重新登录。',
  403: '您没有执行此操作的业务权限。', 404: '记录不存在或您没有访问权限。',
  409: '当前状态不允许此操作，请刷新后确认审核人、状态和有效性。',
  422: '方案未通过生成或保存校验，未返回未经验证的方案。',
  500: '后端处理发生异常，未取得有效结果。请联系维护人员检查错误记录，勿连续重复提交。',
  502: '后端服务处理失败，未取得有效结果。请联系维护人员检查错误记录，勿连续重复提交。',
  503: '服务暂不可用，请联系维护人员检查配置或服务状态。',
}
const codes: Record<string, string> = {
  rate_limited: '操作过于频繁，请稍后再试；本次请求未被处理。',
  customer_search_query_too_long: '客户搜索最多 200 个字符，请缩短后重试；输入未被截断。',
  solution_draft_no_proposals: '模型未生成任何技术建议，未形成可交付方案，未保存方案。请联系售前与维护人员核对生成结果；这不等同于客户信息缺失，勿连续重复生成。',
  solution_export_unsupported_format: '请选择 Word 或 PDF 导出格式。',
  solution_export_not_approved: '当前方案尚未通过技术审核，未导出文件。',
  solution_export_stale: '方案状态、需求或依据已变化，请刷新并核对；未导出文件。',
  solution_export_requirement_changed: '客户需求已改变，请核对当前方案与需求版本；未导出文件。',
  solution_export_changed: '方案状态、需求或依据已变化，请刷新并核对；未导出文件。',
  solution_export_invalid_payload: '方案正文或引用记录不完整，未导出文件。请联系维护人员核对。',
  solution_export_too_large: '导出文件超过 10 MiB 限制，未截断正文。请联系维护人员处理。',
  solution_export_unavailable: '暂时无法导出文件，请联系维护人员检查文档服务，稍后再试。',
  solution_draft_unqualified_precondition: '生成内容的实施前提不充分：核验完成不等于条件满足，未保存方案。请联系售前与维护人员核对前提和后续动作，勿连续重复生成。',
  solution_draft_unconfirmed_assertion: '生成内容把未确认条件写成了确定断言，未保存方案。请联系售前与维护人员核查生成表述和依据，勿连续重复生成。',
  solution_draft_expression_unclassified: '生成内容的规划表达无法可靠识别，未保存方案，需要技术核对。这不等同于客户信息缺失，勿连续重复生成。',
  solution_draft_invalid_response: '模型返回的方案格式不符合生成合同，未保存方案。请联系维护人员核对模型输出格式，勿连续重复生成。',
  solution_needs_sales_clarification: '需求方向尚不明确或客户信息存在冲突，未开始方案生成。请按所选快照中的追问和冲突向客户确认，保存真实需求后创建新分析快照。不要猜测或编造待确认信息。',
  solution_needs_presales_involvement: '客户需求存在技术冲突，未开始方案生成。请联系售前负责人核对部署、安全、环境、集成或技术约束中的冲突；确认后更新需求并创建新分析快照。',
  solution_draft_not_grounded: '生成内容未通过事实依据或技术判断校验，未保存方案。这不等同于客户信息缺失，请联系售前与维护人员核查拒绝记录，勿连续重复生成。',
  invalid_solution_grounding_input: '方案校验输入不符合要求，未保存方案。请联系维护人员检查错误记录。',
  solution_grounding_invalid_response: '校验模型返回了无效结果，未保存方案。请联系维护人员检查错误记录，勿连续重复生成。',
  solution_draft_insufficient_approved_evidence: '当前检索资料缺少已审核、有效且可引用的企业事实，未开始方案生成。请补充相关资料，或请有权限的审核人员核对并审核相关事实后再生成。',
  requirement_analysis_invalid_response: '模型返回的需求分析未通过格式或一致性校验，未保存分析快照。请联系维护人员检查错误记录。',
  llm_provider_error: '模型服务调用失败，未取得有效结果。请联系维护人员检查服务状态，勿连续重复提交。',
  llm_invalid_response: '模型返回了无效响应，未取得有效结果。请联系维护人员检查错误记录。',
  llm_not_configured: '模型服务尚未配置，请联系维护人员检查配置。',
  unsupported_llm_provider: '当前模型服务配置不支持，请联系维护人员检查配置。',
  solution_review_stale: '方案已过期，请基于当前信息生成新版本。',
  solution_review_self_review: '方案作者不能审核自己的版本，请选择独立审核人。',
  solution_review_missing_reviewer: '请先指派售前负责人或提供独立审核人。',
  solution_review_invalid_reviewer: '所选审核人不符合业务审核要求。',
}
export function safeError(error: unknown): string {
  const response = (error as {response?: {status?: number; data?: {code?: string; budget?: unknown}}})?.response
  if (response?.status === 400 && Array.isArray(response.data?.budget) && response.data.budget.length) {
    return '预算格式不正确：请填写大于或等于 0 的金额，最多两位小数；预算未确认时可留空。'
  }
  const localCode = (error as {code?: unknown})?.code
  const code = response?.data?.code || (localCode === 'customer_search_query_too_long' ? localCode : undefined)
  return (code && codes[code]) || messages[response?.status ?? 0] || '请求未完成，请检查网络或稍后刷新确认结果。请勿重复提交生成请求。'
}

export function generationNextAction(error: unknown): {tab:'requirement'|'overview';label:string}|undefined {
  const code = (error as {response?: {data?: {code?: string}}})?.response?.data?.code
  if(code === 'solution_needs_sales_clarification')
    return {tab:'requirement',label:'查看并补充客户需求'}
  if(code === 'solution_needs_presales_involvement')
    return {tab:'overview',label:'查看售前负责人'}
  return undefined
}
