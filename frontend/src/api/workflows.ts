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

export const resumeSolutionWorkflow = async (
  workflowId:string,
  action:
    | {action:'SUBMIT_FOR_REVIEW'}
    | {action:'APPROVE'}
    | {action:'REQUEST_REVISION';return_reason:Uppercase<ReturnReason>;comment:string},
) => (await http.post<SolutionWorkflow>(`${workflowPath(workflowId)}resume/`,action)).data
