import { http } from './http'
import type { Customer, Page } from '../types/domain'

export interface CustomerInput { name:string;industry?:string;company_size?:string;basic_info?:string }

export const searchCustomers = async (query:string,page=1) =>
  (await http.get<Page<Customer>>('/customers/search/',{params:{q:query,page}})).data

export const createCustomer = async (input:CustomerInput) =>
  (await http.post<Customer>('/customers/',input)).data
