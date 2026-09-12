import type { Opportunity } from './domain'

export interface WorkspaceTask {
  solution_draft_id:number
  opportunity_id:number
  project_name:string
  customer_name:string
  solution_version:number
  workflow_id:string|null
  status:string
  updated_at:string
}

export interface SalesWorkspace {
  my_opportunities:Opportunity[]
  tasks:{
    customer_info_required:WorkspaceTask[]
    waiting_for_sales_confirmation:WorkspaceTask[]
    waiting_for_presales_review:WorkspaceTask[]
  }
  recently_updated:Opportunity[]
}

export interface ReviewInboxItem {
  review_id:number
  solution_draft_id:number
  opportunity_id:number
  project_name:string
  customer_name:string
  solution_version:number
  sales_owner_name:string
  status:string
  return_reason:string
  comment:string
  submitted_at:string
  decided_at:string|null
}

export interface ReviewerInbox {
  pending_reviews:ReviewInboxItem[]
  technical_revisions:ReviewInboxItem[]
  recent_reviews:ReviewInboxItem[]
}
