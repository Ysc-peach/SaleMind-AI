import { http } from './http'
import type { Page } from '../types/domain'
import type { Solution, SolutionSummary } from '../types/workflow'
const path=(id:number)=>`/opportunities/${id}/solution-drafts/`
export const listSolutions=async(id:number,page=1)=>(await http.get<Page<SolutionSummary>>(path(id),{params:{page}})).data
export const generateSolution=async(id:number,analysisId:number)=>(await http.post<Solution>(path(id),{analysis_id:analysisId})).data
export const getSolution=async(id:number)=>(await http.get<Solution>(`/solution-drafts/${id}/`)).data
