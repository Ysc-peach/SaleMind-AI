import { http } from './http'
import type { Page, Opportunity } from '../types/domain'
export const listOpportunities = async (page = 1) => (await http.get<Page<Opportunity>>('/opportunities/', { params: { page } })).data
export const getOpportunity = async (id: number) => (await http.get<Opportunity>(`/opportunities/${id}/`)).data
export const saveRequirement = async (id: number, raw_requirement: string) => (await http.patch<Opportunity>(`/opportunities/${id}/`, { raw_requirement })).data
export interface OpportunityInput {project_name:string;customer:number;presales_owner:number|null;raw_requirement:string;budget?:string|null;expected_launch_date?:string|null}
export const createOpportunity = async (input:OpportunityInput) => (await http.post<Opportunity>('/opportunities/',input)).data
