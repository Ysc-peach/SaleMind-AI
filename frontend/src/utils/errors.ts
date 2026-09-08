const messages: Record<number, string> = {
  400: '输入不符合要求，请检查所填字段。', 401: '登录已失效，请重新登录。',
  403: '您没有执行此操作的业务权限。', 404: '记录不存在或您没有访问权限。',
  409: '当前状态不允许此操作，请刷新后确认审核人、状态和有效性。',
  422: '方案未通过生成或保存校验，未返回未经验证的方案。',
}
const codes: Record<string, string> = {
  solution_review_stale: '方案已过期，请基于当前信息生成新版本。',
  solution_review_self_review: '方案作者不能审核自己的版本，请选择独立审核人。',
  solution_review_missing_reviewer: '请先指派售前负责人或提供独立审核人。',
  solution_review_invalid_reviewer: '所选审核人不符合业务审核要求。',
}
export function safeError(error: unknown): string {
  const response = (error as {response?: {status?: number; data?: {code?: string}}})?.response
  const code = response?.data?.code
  return (code && codes[code]) || messages[response?.status ?? 0] || '请求未完成，请检查网络或稍后刷新确认结果。请勿重复提交生成请求。'
}
