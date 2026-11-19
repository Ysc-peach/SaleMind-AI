import { http } from './http'
import type { CaseStudy, Page } from '../types/domain'

export interface CaseStudyInput {
  title: string
  industry: string
  size_band: string
  customer_name?: string
  pain_points?: string
  approach?: string
  results?: string
  referenceable?: boolean
}

export interface CaseFilters {
  industry?: string
  size_band?: string
  referenceable?: boolean
  q?: string
  include_inactive?: boolean
}

export const listCaseStudies = async (
  filters: CaseFilters = {},
  page = 1,
) => {
  const params: Record<string, string | number> = { page }
  // Only the filters the operator actually set go on the wire.
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === '' || value === false) continue
    params[key] = typeof value === 'boolean' ? 'true' : value
  }
  return (await http.get<Page<CaseStudy>>('/case-studies/', { params })).data
}

export const createCaseStudy = async (input: CaseStudyInput) =>
  (await http.post<CaseStudy>('/case-studies/', input)).data

export const updateCaseStudy = async (
  id: number,
  input: Partial<CaseStudyInput>,
) => (await http.patch<CaseStudy>(`/case-studies/${id}/`, input)).data

export const setCaseStudyActive = async (id: number, active: boolean) =>
  (
    await http.post<CaseStudy>(
      `/case-studies/${id}/${active ? 'restore' : 'archive'}/`,
    )
  ).data

/** Ranked by resemblance, so a near miss is still better than nothing. */
export const matchCaseStudies = async (
  industry: string,
  sizeBand?: string,
  limit = 5,
) => {
  const params: Record<string, string | number> = { limit }
  if (industry) params.industry = industry
  if (sizeBand) params.size_band = sizeBand
  return (
    await http.get<{ results: CaseStudy[] }>('/case-studies/match/', { params })
  ).data.results
}
