import { http } from './http'
import type { ReturnReason, SolutionWorkflow } from '../types/workflow'

const collectionPath = (opportunityId:number) => `/opportunities/${opportunityId}/solution-workflows/`
const workflowPath = (workflowId:string) => `/solution-workflows/${workflowId}/`

export const newWorkflowRequestKey = () => globalThis.crypto.randomUUID()

export const startSolutionWorkflow = async (
  opportunityId:number,
  analysisId:number,
  idempotencyKey:string,
) => (await http.post<SolutionWorkflow>(
  collectionPath(opportunityId),
  {analysis_id:analysisId},
  {headers:{'Idempotency-Key':idempotencyKey}},
)).data

export const getSolutionWorkflow = async (workflowId:string) =>
  (await http.get<SolutionWorkflow>(workflowPath(workflowId))).data

// Only a queued or running job is worth polling. Any other status without a
// draft is a real failure and must surface immediately, as before async mode.
const POLLABLE_WORKFLOW_STATUSES = ['QUEUED', 'RUNNING']

/**
 * Poll a workflow that was queued by the worker until its draft exists.
 *
 * The synchronous path already returns a draft, so this resolves immediately.
 */
export const waitForSolutionDraft = async (
  started: SolutionWorkflow,
  {intervalMs = 3000, timeoutMs = 15 * 60 * 1000} = {},
): Promise<SolutionWorkflow> => {
  if (started.solution_draft_id) return started
  if (!POLLABLE_WORKFLOW_STATUSES.includes(started.status)) return started
  const deadline = Date.now() + timeoutMs
  let current = started
  while (Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, intervalMs))
    current = await getSolutionWorkflow(started.workflow_id)
    if (current.solution_draft_id) return current
    if (!POLLABLE_WORKFLOW_STATUSES.includes(current.status)) return current
  }
  throw new Error('workflow_timeout')
}

export const resumeSolutionWorkflow = async (
  workflowId:string,
  action:
    | {action:'SUBMIT_FOR_REVIEW'}
    | {action:'APPROVE'}
    | {action:'REQUEST_REVISION';return_reason:Uppercase<ReturnReason>;comment:string},
) => (await http.post<SolutionWorkflow>(`${workflowPath(workflowId)}resume/`,action)).data
