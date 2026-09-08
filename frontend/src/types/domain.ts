export type Role = 'admin' | 'sales' | 'presales'
export interface User { id: number; username: string; role: Role; email: string; first_name: string; last_name: string }
export interface Page<T> { count: number; next: string | null; previous: string | null; results: T[] }
export interface Opportunity { id: number; project_name: string; customer: number; sales_owner: number; presales_owner: number | null; stage: string; status: string; budget: string | null; expected_launch_date: string | null; raw_requirement?: string; updated_at: string }
