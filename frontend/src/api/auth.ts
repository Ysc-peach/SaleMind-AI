import axios from 'axios'
import { http } from './http'
import type { User } from '../types/domain'

export const loginRequest = async (username: string, password: string) =>
  (await axios.post<{access: string; refresh: string}>('/api/auth/login/', { username, password })).data
export const refreshRequest = async (refresh: string) =>
  (await axios.post<{access: string}>('/api/auth/refresh/', { refresh })).data
export const logoutRequest = async (refresh: string) =>
  axios.post('/api/auth/logout/', { refresh })
export const changePasswordRequest = async (currentPassword: string, newPassword: string) =>
  http.post('/auth/password/', { current_password: currentPassword, new_password: newPassword })
export const meRequest = async () => (await http.get<User>('/auth/me/')).data
