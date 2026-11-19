import { http } from './http'
import type { Competitor, CompetitorStatement, Page } from '../types/domain'

export const listCompetitors = async (
  filters: { q?: string; include_inactive?: boolean } = {},
  page = 1,
) => {
  const params: Record<string, string | number> = { page }
  if (filters.q) params.q = filters.q
  if (filters.include_inactive) params.include_inactive = '1'
  return (await http.get<Page<Competitor>>('/competitors/', { params })).data
}

export const createCompetitor = async (input: {
  name: string
  aliases?: string
}) => (await http.post<Competitor>('/competitors/', input)).data

export const setCompetitorActive = async (id: number, active: boolean) =>
  (
    await http.post<Competitor>(
      `/competitors/${id}/${active ? 'restore' : 'archive'}/`,
    )
  ).data

export interface StatementInput {
  dimension: string
  statement: string
  source_url: string
  published_on?: string | null
}

export const listStatements = async (
  competitorId: number,
  filters: { dimension?: string; status?: string } = {},
  page = 1,
) => {
  const params: Record<string, string | number> = { page }
  for (const [key, value] of Object.entries(filters)) {
    if (value) params[key] = value
  }
  return (
    await http.get<Page<CompetitorStatement>>(
      `/competitors/${competitorId}/statements/`,
      { params },
    )
  ).data
}

export const createStatement = async (
  competitorId: number,
  input: StatementInput,
) =>
  (
    await http.post<CompetitorStatement>(
      `/competitors/${competitorId}/statements/`,
      input,
    )
  ).data

/** Approve or reject one statement; only an administrator may call this. */
export const decideStatement = async (id: number, approve: boolean) =>
  (
    await http.post<CompetitorStatement>(
      `/competitor-statements/${id}/${approve ? 'approve' : 'reject'}/`,
    )
  ).data
