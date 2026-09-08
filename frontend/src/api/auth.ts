import axios from 'axios'
import { http } from './http'
import type { User } from '../types/domain'

export const loginRequest = async (username: string, password: string) =>
  (await axios.post<{access: string; refresh: string}>('/api/auth/login/', { username, password })).data
export const refreshRequest = async (refresh: string) =>
  (await axios.post<{access: string}>('/api/auth/refresh/', { refresh })).data
export const meRequest = async () => (await http.get<User>('/auth/me/')).data
