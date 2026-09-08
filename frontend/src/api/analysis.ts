import { http } from './http'
import type { Page } from '../types/domain'
import type { Analysis, AnalysisSummary } from '../types/workflow'
const path=(id:number)=>`/opportunities/${id}/ai/requirement-analyses/`
export const analysisHistory=async(id:number,page=1)=>(await http.get<Page<AnalysisSummary>>(path(id),{params:{page}})).data
export const getAnalysis=async(id:number,analysisId:number)=>(await http.get<Analysis>(`${path(id)}${analysisId}/`)).data
export const latestAnalysis=async(id:number)=>(await http.get<Analysis>(`${path(id)}latest/`)).data
export const createAnalysis=async(id:number)=>(await http.post<Analysis>(path(id),{})).data
