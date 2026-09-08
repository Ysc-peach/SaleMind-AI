import { beforeEach, describe, expect, it, vi } from 'vitest'
import axios, { AxiosError, type AxiosAdapter } from 'axios'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../stores/auth'
import { http } from '../api/http'

const user = { id: 1, username: 'sales', role: 'sales', email: '', first_name: '', last_name: '' }
let calls: string[]
let failLogin = false
let failRefresh = false
let always401 = false
const adapter: AxiosAdapter = async config => {
  const url = config.url!.replace(/^\/api/, '')
  calls.push(url)
  const reject = () => { throw new AxiosError('redacted', 'ERR_BAD_REQUEST', config, null, { data: {}, status: 401, statusText: '', headers: {}, config }) }
  let data: unknown = {}
  if (url === '/auth/login/') { if (failLogin) reject(); data = { access: 'test-access', refresh: 'test-refresh' } }
  else if (url === '/auth/refresh/') { await new Promise(r => setTimeout(r, 10)); if (failRefresh) reject(); data = { access: 'new-access' } }
  else if (url === '/auth/me/') data = user
  else { if (always401 || config.headers.Authorization !== 'Bearer new-access') reject(); data = { ok: true } }
  return { data, status: 200, statusText: 'OK', headers: {}, config }
}

beforeEach(() => {
  setActivePinia(createPinia()); sessionStorage.clear(); calls = []
  failLogin = false; failRefresh = false; always401 = false
  axios.defaults.adapter = adapter; http.defaults.adapter = adapter
})
describe('authentication', () => {
  it('logs in with me-derived role and persists only refresh token', async () => {
    const auth = useAuthStore(); await auth.login('sales', 'synthetic')
    expect(auth.user).toEqual(user); expect(auth.accessToken).toBe('test-access')
    expect(sessionStorage.getItem('salesmind.refresh')).toBe('test-refresh')
    expect(sessionStorage.getItem('access')).toBeNull()
  })
  it('rejects failed login and clears authentication', async () => {
    failLogin = true; const auth = useAuthStore()
    await expect(auth.login('sales', 'bad')).rejects.toBeDefined()
    expect(auth.user).toBeNull(); expect(sessionStorage.length).toBe(0)
  })
  it('restores a session through refresh and me', async () => {
    sessionStorage.setItem('salesmind.refresh', 'test-refresh')
    const auth = useAuthStore(); await auth.restore()
    expect(auth.user?.id).toBe(1); expect(calls).toEqual(['/auth/refresh/', '/auth/me/'])
  })
  it('refreshes once for concurrent 401 responses', async () => {
    const auth = useAuthStore(); await auth.login('sales', 'synthetic')
    const responses = await Promise.all([http.get('/protected/a'), http.get('/protected/b')])
    expect(responses.every(r => r.data.ok)).toBe(true)
    expect(calls.filter(p => p === '/auth/refresh/')).toHaveLength(1)
  })
  it('clears state and signals login when refresh fails', async () => {
    const auth = useAuthStore(); await auth.login('sales', 'synthetic'); failRefresh = true
    const expired = vi.fn(); window.addEventListener('salesmind:expired', expired, { once: true })
    await expect(http.get('/protected/a')).rejects.toBeDefined()
    expect(auth.user).toBeNull(); expect(sessionStorage.length).toBe(0); expect(expired).toHaveBeenCalledOnce()
  })
  it('does not replay a request more than once', async () => {
    const auth = useAuthStore(); await auth.login('sales', 'synthetic'); always401 = true
    await expect(http.get('/protected/a')).rejects.toBeDefined()
    expect(calls.filter(p => p === '/protected/a')).toHaveLength(2)
    expect(calls.filter(p => p === '/auth/refresh/')).toHaveLength(1)
  })
  it('does not refresh again when a late 401 used the previous token', async () => {
    const auth=useAuthStore(); await auth.login('sales','synthetic')
    http.defaults.adapter=async config=>{
      if(config.url==='/protected/late'&&config.headers.Authorization==='Bearer test-access')await new Promise(r=>setTimeout(r,40))
      return adapter(config)
    }
    await Promise.all([http.get('/protected/a'),http.get('/protected/late')])
    expect(calls.filter(p=>p==='/auth/refresh/')).toHaveLength(1)
  })
  it('never replays an old session request under a new login',async()=>{
    const auth=useAuthStore(); await auth.login('sales','synthetic')
    let release:()=>void=()=>{}
    const gate=new Promise<void>(r=>{release=r})
    http.defaults.adapter=async config=>{if(config.url==='/protected/old')await gate;return adapter(config)}
    const old=http.get('/protected/old').catch(()=>null)
    await new Promise(r=>setTimeout(r,0)); auth.logout(); await auth.login('sales','synthetic'); release(); await old
    expect(calls.filter(p=>p==='/protected/old')).toHaveLength(1)
    expect(calls.filter(p=>p==='/auth/refresh/')).toHaveLength(0)
  })
  it('discards a late non-401 error from a replaced session',async()=>{
    const auth=useAuthStore(); await auth.login('sales','synthetic')
    let release:()=>void=()=>{}; const gate=new Promise<void>(r=>{release=r})
    http.defaults.adapter=async config=>{
      if(config.url==='/protected/conflict'){
        await gate
        throw new AxiosError('old-conflict','ERR_BAD_REQUEST',config,null,{data:{},status:409,statusText:'',headers:{},config})
      }
      return adapter(config)
    }
    const pending=http.get('/protected/conflict').catch(error=>error)
    await new Promise(r=>setTimeout(r,0)); auth.logout(); await auth.login('sales','synthetic'); release()
    expect((await pending).message).toBe('session_changed')
    expect(calls.filter(path=>path==='/protected/conflict')).toHaveLength(0)
  })
})
