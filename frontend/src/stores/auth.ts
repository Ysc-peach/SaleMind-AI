import { defineStore } from 'pinia'
import { ref } from 'vue'
import { bindAuth } from '../api/http'
import { loginRequest, meRequest, refreshRequest } from '../api/auth'
import type { User } from '../types/domain'

const storageKey = 'salesmind.refresh'
export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref('')
  const user = ref<User | null>(null)
  const restored = ref(false)
  let refreshing: Promise<void> | undefined
  let restoring: Promise<void> | undefined
  let epoch = 0
  function logout() { epoch++; accessToken.value = ''; user.value = null; sessionStorage.removeItem(storageKey) }
  function expire() { logout(); window.dispatchEvent(new Event('salesmind:expired')) }
  function refresh() {
    if (refreshing) return refreshing
    const refreshToken = sessionStorage.getItem(storageKey)
    if (!refreshToken) return Promise.reject(new Error('authentication_required'))
    const current = epoch
    refreshing = refreshRequest(refreshToken).then(result => {
      if (epoch !== current) throw new Error('session_changed')
      accessToken.value = result.access
    }).finally(() => { refreshing = undefined })
    return refreshing
  }
  async function login(username: string, password: string) {
    logout()
    try {
      const result = await loginRequest(username, password)
      accessToken.value = result.access; sessionStorage.setItem(storageKey, result.refresh)
      user.value = await meRequest(); restored.value = true
    } catch (error) { logout(); throw error }
  }
  function restore() {
    if (restored.value) return Promise.resolve()
    if (restoring) return restoring
    restoring = (async () => {
      try { if (sessionStorage.getItem(storageKey)) { await refresh(); user.value = await meRequest() } }
      catch { logout() }
      finally { restored.value = true; restoring = undefined }
    })()
    return restoring
  }
  bindAuth({ token: () => accessToken.value, refresh, expire })
  return { accessToken, user, restored, login, logout, restore, refresh }
})
