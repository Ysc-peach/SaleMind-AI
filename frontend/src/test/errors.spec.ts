import { describe, expect, it } from 'vitest'
import { safeError, generationNextAction } from '../utils/errors'

describe('safe generation failure messages', () => {
  it('explains an empty generated solution without blaming customer information', () => {
    const error = { response: { status: 422, data: {
      code: 'solution_draft_no_proposals', message: 'private customer and provider output',
    } } }
    const message = safeError(error)
    expect(message).toContain('未形成可交付方案')
    expect(message).toContain('未保存')
    expect(message).not.toContain('private')
    expect(message).not.toContain('补充客户需求')
    expect(generationNextAction(error)).toBeUndefined()
  })
  it.each([
    ['solution_draft_unqualified_precondition', '前提', '核验完成不等于条件满足'],
    ['solution_draft_unconfirmed_assertion', '未确认', '断言'],
    ['solution_draft_expression_unclassified', '表达', '技术核对'],
    ['solution_draft_invalid_response', '格式', '格式'],
  ])('keeps %s technical rather than customer clarification', (code, subject, reason) => {
    const error={response:{status:422,data:{code,message:'private raw claim',detail:'secret'}}}
    const message=safeError(error)
    expect(message).toContain(subject)
    expect(message).toContain(reason)
    expect(message).toContain('未保存')
    expect(message).not.toContain('private')
    expect(message).not.toContain('secret')
    expect(message).not.toContain('补充客户需求')
    expect(generationNextAction(error)).toBeUndefined()
  })
  it.each([
    ['requirement_analysis_invalid_response', '需求分析', '校验'],
    ['llm_provider_error', '模型服务', '失败'],
    ['llm_invalid_response', '模型', '无效'],
    ['llm_not_configured', '模型服务', '配置'],
    ['unsupported_llm_provider', '模型服务', '不支持'],
  ])('distinguishes %s without exposing server content', (code, subject, reason) => {
    const message = safeError({ response: { status: 502, data: {
      code, message: 'secret API key', detail: 'raw customer/provider output',
    } } })
    expect(message).toContain(subject)
    expect(message).toContain(reason)
    expect(message).not.toContain('请检查网络')
    expect(message).not.toContain('secret')
    expect(message).not.toContain('raw customer')
  })

  it.each([502, 503])('does not mislabel HTTP %s as a browser network failure', status => {
    const message = safeError({ response: { status, data: { code: 'unknown', message: 'secret' } } })
    expect(message).toContain('服务')
    expect(message).not.toContain('请检查网络')
    expect(message).not.toContain('secret')
  })

  it.each([
    ['solution_draft_not_grounded', '依据'],
    ['invalid_solution_grounding_input', '校验'],
    ['solution_grounding_invalid_response', '校验'],
  ])('explains a typed %s rejection without leaking backend diagnostics', (code, reason) => {
    const message = safeError({ response: { status: 422, data: {
      code, message: 'private rejected claim and API key',
    } } })
    expect(message).toContain(reason)
    expect(message).toContain('未保存')
    expect(message).not.toContain('网络')
    expect(message).not.toContain('private')
  })

  it('does not label HTTP 500 as an uncertain network result', () => {
    const message = safeError({ response: { status: 500, data: { message: 'private exception' } } })
    expect(message).toContain('后端')
    expect(message).not.toContain('请检查网络')
    expect(message).not.toContain('private')
  })

  it('keeps uncertain transport outcomes distinct from server failures', () => {
    expect(safeError({})).toContain('请勿重复提交')
  })

  it('explains missing authorized evidence without suggesting repeated generation', () => {
    const message = safeError({ response: { status: 422, data: {
      code: 'solution_draft_insufficient_approved_evidence', message: 'private customer text',
    } } })
    expect(message).toContain('已审核')
    expect(message).toContain('可引用')
    expect(message).toContain('资料')
    expect(message).not.toContain('网络')
    expect(message).not.toContain('保存校验')
    expect(message).not.toContain('private customer')
  })

  it.each([
    ['solution_needs_sales_clarification', '客户确认'],
    ['solution_needs_presales_involvement', '技术冲突'],
  ])('routes formal readiness failure %s to the responsible person', (code, reason) => {
    const message = safeError({ response: { status: 422, data: { code, detail: 'private text' } } })
    expect(message).toContain(reason)
    expect(message).toContain('未开始')
    expect(message).not.toContain('保存校验')
    expect(message).not.toContain('private')
  })

  it('does not blame missing customer information for a content veto', () => {
    const message = safeError({ response: { status: 422, data: { code: 'solution_draft_not_grounded' } } })
    expect(message).toContain('生成内容')
    expect(message).toContain('不等同于客户信息缺失')
    expect(message).not.toContain('请补充客户需求')
  })
})
