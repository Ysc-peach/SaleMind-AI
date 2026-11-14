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

export interface AuditEvents {
  reviews: AuditReview[]
  generations: AuditGeneration[]
  limit: number
}

export const auditEvents = async () => (await http.get<AuditEvents>('/audit/events/')).data
