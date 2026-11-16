import { http } from './http'

export interface AuditReview {
  id: number
  opportunity_id: number
  project_name: string
  submitted_by: string
  reviewer: string
  status: string
  return_reason: string
  submitted_at: string
  decided_at: string | null
}

export interface AuditGeneration {
  id: number
  opportunity_id: number
  project_name: string
  requested_by: string
  status: string
  error_code: string
  created_at: string
  finished_at: string | null
}

export interface AuditPage<T> {
  count: number
  results: T[]
}

export interface AuditFilters {
  actor?: string
  status?: string
  date_from?: string
  date_to?: string
}

export interface AuditEvents {
  page: number
  page_size: number
  filters: Required<AuditFilters> & { date_from: string | null; date_to: string | null }
  reviews: AuditPage<AuditReview>
  generations: AuditPage<AuditGeneration>
}

export const auditEvents = async (
  filters: AuditFilters = {},
  page = 1,
  pageSize = 20,
) => {
  const params: Record<string, string | number> = { page, page_size: pageSize }
  // Unset filters are omitted rather than sent as empty strings, so the request
  // URL stays readable in logs and matches what the operator actually chose.
  for (const [key, value] of Object.entries(filters)) {
    if (value) params[key] = value
  }
  return (await http.get<AuditEvents>('/audit/events/', { params })).data
}
