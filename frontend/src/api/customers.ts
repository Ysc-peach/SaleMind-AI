import { http } from './http'
import type { Customer, Page } from '../types/domain'

export interface CustomerInput { name:string;industry?:string;company_size?:string;basic_info?:string }

export const searchCustomers = async (query:string,page=1,includeInactive=false) => {
  const normalized = query.trim()
  // Count Unicode code points like the server, not UTF-16 code units.
  if ([...normalized].length > 200) {
    throw Object.assign(new Error('Customer search input exceeds the limit.'), {
      code: 'customer_search_query_too_long',
    })
  }
  // Only sent when asked for: the server rejects the parameter for non-admins.
  const params: Record<string, string | number> = { q: normalized, page }
  if (includeInactive) params.include_inactive = '1'
  return (await http.get<Page<Customer>>('/customers/search/',{params})).data
}

export const createCustomer = async (input:CustomerInput) =>
  (await http.post<Customer>('/customers/',input)).data

export const updateCustomer = async (id:number, input:Partial<CustomerInput>) =>
  (await http.patch<Customer>(`/customers/${id}/`,input)).data

/** Archive or restore a customer. Administrator only; the server enforces it. */
export const setCustomerActive = async (id:number, active:boolean) =>
  (await http.post<Customer>(`/customers/${id}/${active ? 'enable' : 'disable'}/`)).data
