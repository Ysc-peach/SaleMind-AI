export interface AnalysisSummary { id:number; summary:string; analysis_version:string; created_at:string }
export interface Analysis extends AnalysisSummary {
  requirements:Record<string,{status:string;value:string|null;evidence:string|null}>
  conflicts:{fields:string[];description:string}[]
  clarifying_questions:{field:string;question:string}[]
}
export interface Statement {type:string;text:string;citations:string[]}
export interface SolutionSummary {id:number;opportunity:number;analysis_id:number;version:number;title:string;review_status:string;is_stale:boolean;stale_reasons:string[];created_by:number;created_at:string}
export interface Solution extends SolutionSummary {
  draft_payload:{title:string;executive_summary:Statement[];solution_sections:{key:string;title:string;statements:Statement[]}[];assumptions:{text:string;related_fields:string[]}[]}
  provenance:{statement_path:string;citation_label:string;source_document_id:number;source_excerpt:string}[]
}
export type ReturnReason = 'customer_info_required'|'technical_revision_required'
export interface Review {id:number;solution_draft:number;submitted_by:number;reviewer:number;status:string;return_reason:ReturnReason|'';comment:string;submitted_at:string;decided_at:string|null}
