import { http } from './http'
import type { Page, Opportunity } from '../types/domain'
export const listOpportunities = async (page = 1, includeInactive = false) => {
  // The archive flag is only requested when asked for; the server refuses it
  // for anyone but an administrator.
  const params: Record<string, string | number> = { page }
  if (includeInactive) params.include_inactive = '1'
  return (await http.get<Page<Opportunity>>('/opportunities/', { params })).data
}
export const setOpportunityActive = async (id: number, active: boolean) =>
  (await http.post<Opportunity>(`/opportunities/${id}/${active ? 'enable' : 'disable'}/`)).data
export const getOpportunity = async (id: number) => (await http.get<Opportunity>(`/opportunities/${id}/`)).data
export const saveRequirement = async (id: number, raw_requirement: string) => (await http.patch<Opportunity>(`/opportunities/${id}/`, { raw_requirement })).data
export const savePresalesOwner = async (id: number, presales_owner: number | null): Promise<void> => {
  await http.patch(`/opportunities/${id}/`, { presales_owner })
}
export interface OpportunityInput {project_name:string;customer:number;presales_owner:number|null;raw_requirement:string;budget?:string|null;expected_launch_date?:string|null}
export const createOpportunity = async (input:OpportunityInput) => (await http.post<Opportunity>('/opportunities/',input)).data
