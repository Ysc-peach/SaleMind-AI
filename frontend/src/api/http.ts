import axios from 'axios'

interface AuthBridge { token: () => string; refresh: () => Promise<void>; expire: () => void }
let auth: AuthBridge | undefined
export function bindAuth(bridge: AuthBridge) { auth = bridge }
export const http = axios.create({ baseURL: '/api' })
http.interceptors.request.use(config => {
  const token = auth?.token()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
http.interceptors.response.use(response => response, async error => {
  const config = error.config
  if (error.response?.status !== 401 || !config || !auth) throw error
  if (config._authReplayed) { auth.expire(); throw error }
  config._authReplayed = true
  try { await auth.refresh() } catch { auth.expire(); throw error }
  return http.request(config)
})
