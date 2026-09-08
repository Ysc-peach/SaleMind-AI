import { http } from './http'
import type { Page, Opportunity } from '../types/domain'
export const listOpportunities = async (page = 1) => (await http.get<Page<Opportunity>>('/opportunities/', { params: { page } })).data
export const getOpportunity = async (id: number) => (await http.get<Opportunity>(`/opportunities/${id}/`)).data
export const saveRequirement = async (id: number, raw_requirement: string) => (await http.patch<Opportunity>(`/opportunities/${id}/`, { raw_requirement })).data
