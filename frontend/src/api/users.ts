import { http } from './http'
import type { Page, PresalesOption } from '../types/domain'

/** The assignable presales people, read-only and available to every role. */
export const listPresalesOptions = async () =>
  (await http.get<PresalesOption[]>('/users/presales-options/')).data

export interface ManagedUser {
  id: number
  username: string
  email: string
  first_name: string
  last_name: string
  role: string
  role_label: string
  is_active: boolean
  date_joined: string
  last_login: string | null
}

export interface UserFilters {
  q?: string
  role?: string
  include_inactive?: boolean
}

export const listUsers = async (filters: UserFilters = {}, page = 1) => {
  const params: Record<string, string | number> = { page }
  if (filters.q) params.q = filters.q
  if (filters.role) params.role = filters.role
  if (filters.include_inactive) params.include_inactive = '1'
  return (await http.get<Page<ManagedUser>>('/users/', { params })).data
}

export interface CreateUserInput {
  username: string
  email: string
  role: string
  password: string
  first_name?: string
  last_name?: string
}

export const createUser = async (input: CreateUserInput) =>
  (await http.post<ManagedUser>('/users/', input)).data

export const updateUser = async (
  id: number,
  patch: { role?: string; email?: string; first_name?: string; last_name?: string },
) => (await http.patch<ManagedUser>(`/users/${id}/`, patch)).data

/** Stop or restore an account; the server refuses self-deactivation. */
export const setUserActive = async (id: number, active: boolean) =>
  (
    await http.post<ManagedUser>(
      `/users/${id}/${active ? 'activate' : 'deactivate'}/`,
    )
  ).data

export const resetUserPassword = async (id: number, password: string) =>
  (await http.post(`/users/${id}/password/`, { password })).data as never
