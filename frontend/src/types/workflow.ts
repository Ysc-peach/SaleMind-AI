export interface AnalysisSummary { id:number; summary:string; analysis_version:string; created_at:string }
export interface Analysis extends AnalysisSummary {
  requirements:Record<string,{status:string;value:string|null;evidence:string|null}>
  conflicts:{fields:string[];description:string}[]
  clarifying_questions:{field:string;question:string}[]
}

export interface Statement {type:string;text:string;citations:string[]}
interface SolutionSummaryBase {id:number;opportunity:number;analysis_id:number;version:number;title:string;review_status:string;is_stale:boolean;stale_reasons:string[];created_by:number;created_at:string}
export interface SolutionSummaryV1 extends SolutionSummaryBase {schema_version:1}
export interface SolutionSummaryV2 extends SolutionSummaryBase {schema_version:2}
export type SolutionSummary = SolutionSummaryV1 | SolutionSummaryV2

export interface SolutionV1 extends SolutionSummaryV1 {
  workflow_id:string|null
  draft_payload:{title:string;executive_summary:Statement[];solution_sections:{key:string;title:string;statements:Statement[]}[];assumptions:{text:string;related_fields:string[]}[]}
  provenance:{statement_path:string;citation_label:string;source_document_id:number;source_excerpt:string}[]
}

export type V2ClaimType='customer_fact'|'enterprise_fact'|'proposal'|'assumption'|'unresolved'
export interface V2Claim {claim_id:string;statement_type:V2ClaimType;text:string;citations:string[];related_requirement_fields:string[]}
export interface V2Payload {
  title:string
  claims:V2Claim[]
  executive_summary:string[]
  customer_context:{confirmed_claim_ids:string[];unresolved_claim_ids:string[];requirement_fields:{field:string;status:string;claim_ids:string[]}[]}
  proposed_solution:{overview_claim_ids:string[];capability_groups:{group_id:string;title:string;claim_ids:string[]}[]}
  architecture:{overview_claim_ids:string[];components:{component_id:string;name:string;identity_claim_id?:string|null;responsibility_claim_ids:string[];rationale_claim_ids:string[];dependency_component_ids:string[];interface_claim_ids:string[]}[];flows?:{flow_type:'request'|'data';source_component_id:string;target_component_id:string}[]}
  deployment_and_integration:{block_id:string;topic:string;title:string;claim_ids:string[]}[]
  implementation_plan:{phases:{phase_id:string;name:string;objective_claim_ids:string[];task_claim_ids:string[];owner_roles:string[];deliverable_claim_ids:string[];dependency_phase_ids:string[];acceptance_criterion_ids:string[];timing_claim_id:string|null;timing_classification:string|null}[]}
  risks:{risk_id:string;condition_claim_id:string;impact_claim_ids:string[];mitigation_claim_ids:string[];trigger_claim_ids:string[]}[]
  acceptance_criteria:{criterion_id:string;claim_id:string;classification:string}[]
  milestones:{milestone_id:string;name:string;related_phase_ids:string[];outcome_claim_ids:string[];timing_claim_id:string|null;timing_classification:string|null}[]
  assumptions:string[]
  open_questions:{question_id:string;requirement_field:string;requirement_status:string;unresolved_claim_id:string}[]
  out_of_scope:{scope_id:string;claim_id:string;classification:string}[]
}
export interface SafeSolutionSource {source_id:string;document_id:number;document_title:string;source_excerpt:string}
export interface SolutionV2 extends SolutionSummaryV2 {
  workflow_id:string|null
  draft_payload:V2Payload
  source_registry:SafeSolutionSource[]
  claim_sources:Record<string,string[]>
}
export type Solution = SolutionV1 | SolutionV2

export type ReturnReason = 'customer_info_required'|'technical_revision_required'
export interface Review {id:number;solution_draft:number;submitted_by:number;reviewer:number;status:string;return_reason:ReturnReason|'';comment:string;submitted_at:string;decided_at:string|null}

export type SolutionWorkflowStatus =
  | 'GENERATING'
  | 'WAITING_FOR_SALES_CONFIRMATION'
  | 'WAITING_FOR_PRESALES_REVIEW'
  | 'APPROVED'
  | 'CUSTOMER_INFO_REQUIRED'
  | 'TECHNICAL_REVISION_REQUIRED'
  | 'BLOCKED'
  | 'FAILED'
  | 'CONFLICT'
export type SolutionWorkflowAction = 'SUBMIT_FOR_REVIEW'|'APPROVE'|'REQUEST_REVISION'
export interface SolutionWorkflow {
  workflow_id:string
  status:SolutionWorkflowStatus
  solution_draft_id:number|null
  solution_version:number|null
  solution_review_id:number|null
  reviewer_id:number|null
  allowed_actions:SolutionWorkflowAction[]
  error_code:string
}
