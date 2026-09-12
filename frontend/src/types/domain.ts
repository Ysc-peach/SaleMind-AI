export type Role = 'admin' | 'sales' | 'presales'
export interface User { id: number; username: string; role: Role; email: string; first_name: string; last_name: string }
export interface Page<T> { count: number; next: string | null; previous: string | null; results: T[] }
export interface Opportunity { id: number; project_name: string; customer: number; customer_name?: string; sales_owner: number; sales_owner_name?: string; presales_owner: number | null; presales_owner_name?: string; stage: string; status: string; budget: string | null; expected_launch_date: string | null; raw_requirement?: string; updated_at: string }
export interface Customer { id:number; name:string; industry:string; company_size:string; basic_info:string; opportunities:{id:number;project_name:string;stage:string;status:string;is_mine:boolean;is_followed_by_other_sales:boolean}[] }
export interface PresalesOption { id:number;username:string;first_name:string;last_name:string }
