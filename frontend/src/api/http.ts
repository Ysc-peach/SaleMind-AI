import axios from 'axios'

interface AuthBridge { token: () => string; session: () => number; refresh: () => Promise<void>; expire: () => void }
declare module 'axios' { interface InternalAxiosRequestConfig { _authSession?:number; _authReplayed?:boolean } }
let auth: AuthBridge | undefined
export function bindAuth(bridge: AuthBridge) { auth = bridge }
export const http = axios.create({ baseURL: '/api' })
http.interceptors.request.use(config => {
  if(config._authSession !== undefined && config._authSession !== auth?.session()) throw new Error('session_changed')
  config._authSession = auth?.session()
  const token = auth?.token()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
http.interceptors.response.use(response => {
  if(response.config._authSession !== auth?.session()) throw new Error('session_changed')
  return response
}, async error => {
  const config = error.config
  if (error.response?.status !== 401 || !config || !auth) throw error
  if(config._authSession !== auth.session()) throw error
  if (config._authReplayed) { auth.expire(); throw error }
  config._authReplayed = true
  try {
    if(!auth.token() || config.headers.Authorization === `Bearer ${auth.token()}`) await auth.refresh()
  } catch { if(config._authSession===auth.session())auth.expire(); throw error }
  return http.request(config)
})
