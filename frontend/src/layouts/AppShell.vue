<script setup lang="ts">
import { useAuthStore } from '../stores/auth'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { label } from '../utils/labels'
import { changePasswordRequest } from '../api/auth'
import { reviewSummary } from '../api/reviews'
const auth = useAuthStore(), router = useRouter()
type NavItem = { to: string; label: string; badge?: number }
const pendingReviews = ref(0)
async function loadPendingReviews() {
  // Skipping when unauthenticated keeps the shell from firing a doomed request
  // during login and in component tests that only assert layout.
  if (auth.user?.role !== 'presales' || !auth.accessToken) { pendingReviews.value = 0; return }
  try { pendingReviews.value = (await reviewSummary()).total }
  catch { pendingReviews.value = 0 }
}
const nav = computed<NavItem[]>(() => auth.user?.role === 'sales' ? [
  {to:'/workspace',label:'工作台'}, {to:'/opportunities',label:'商机'}, {to:'/customers',label:'客户'},
] : auth.user?.role === 'presales' ? [
  {to:'/workspace',label:'工作台'},
  {to:'/reviews',label:'待审核',badge:pendingReviews.value},
  {to:'/opportunities',label:'商机'},
] : [{to:'/workspace',label:'工作台'},{to:'/opportunities',label:'商机'}])
onMounted(loadPendingReviews)
// Reviews are decided elsewhere, so refresh the badge whenever the user moves
// or the session's access token changes.
watch(
  () => [router.currentRoute.value.path, auth.accessToken] as const,
  loadPendingReviews,
)
function logout() { auth.logout(); router.replace('/login') }

const passwordOpen = ref(false), passwordBusy = ref(false), passwordError = ref('')
const passwordForm = reactive({ current: '', next: '', confirm: '' })
function openPassword() {
  passwordForm.current = ''; passwordForm.next = ''; passwordForm.confirm = ''
  passwordError.value = ''; passwordOpen.value = true
}
function closePassword() { if (!passwordBusy.value) passwordOpen.value = false }
function passwordErrorText(error: unknown) {
  const data = (error as {response?:{data?:Record<string, unknown>}})?.response?.data ?? {}
  const field = (data.current_password ?? data.new_password) as string[] | string | undefined
  if (Array.isArray(field) && field.length) return String(field[0])
  if (typeof field === 'string') return field
  return '密码未修改，请核对当前密码与新密码要求。'
}
async function submitPassword() {
  passwordError.value = ''
  if (passwordForm.next !== passwordForm.confirm) { passwordError.value = '两次输入的新密码不一致。'; return }
  passwordBusy.value = true
  try {
    await changePasswordRequest(passwordForm.current, passwordForm.next)
    // The server revokes every session, so the local one must go too.
    passwordOpen.value = false; logout()
  } catch (error) { passwordError.value = passwordErrorText(error) }
  finally { passwordBusy.value = false }
}
</script>
<template><div class="app-shell responsive-app-shell"><aside class="app-sidebar"><RouterLink to="/workspace" class="brand">S<span>SalesMind AI</span></RouterLink><p class="nav-caption">售前协作</p><nav class="side-nav"><RouterLink v-for="item in nav" :key="item.to" :to="item.to" class="nav-item">{{ item.label }}<span v-if="item.badge" class="nav-badge" data-test="review-badge">{{ item.badge > 99 ? '99+' : item.badge }}</span></RouterLink></nav><div class="sidebar-note">需求有依据<br>方案可追溯<br>审核留记录</div></aside><div class="app-body shrinkable-app-body"><header><span>企业智能售前与解决方案助手</span><div>{{ auth.user?.first_name || auth.user?.username }} <el-tag size="small">{{ label(auth.user?.role ?? '') }}</el-tag><el-button text data-test="open-password" @click="openPassword">修改密码</el-button><el-button text @click="logout">退出登录</el-button></div></header><main class="content shrinkable-main-content"><RouterView :key="$route.path" /></main><div v-if="passwordOpen" class="password-overlay" role="dialog" aria-modal="true" aria-label="修改密码"><form class="password-card" data-test="password-form" @submit.prevent="submitPassword"><h3>修改密码</h3><p class="muted">修改后所有设备都需要重新登录。</p><label>当前密码<input v-model="passwordForm.current" data-test="password-current" type="password" autocomplete="current-password" required /></label><label>新密码<input v-model="passwordForm.next" data-test="password-next" type="password" autocomplete="new-password" required /></label><label>确认新密码<input v-model="passwordForm.confirm" data-test="password-confirm" type="password" autocomplete="new-password" required /></label><p v-if="passwordError" class="notice" role="alert" data-test="password-error">{{ passwordError }}</p><div class="row"><el-button :disabled="passwordBusy" @click="closePassword">取消</el-button><el-button type="primary" native-type="submit" :loading="passwordBusy">确认修改</el-button></div></form></div></div></div></template>
<style scoped>
.password-overlay { position: fixed; inset: 0; z-index: 40; display: flex; align-items: center; justify-content: center; background: rgba(15, 23, 42, .45); }
.password-card { width: min(380px, 92vw); display: flex; flex-direction: column; gap: 12px; padding: 24px; border-radius: 12px; background: #fff; box-shadow: 0 18px 48px rgba(15, 23, 42, .24); }
.password-card h3 { margin: 0; font-size: 18px; }
.password-card label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: #475569; }
.password-card input { padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 14px; }
.password-card .row { display: flex; justify-content: flex-end; gap: 8px; }
.nav-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 18px; height: 18px; margin-left: 6px; padding: 0 5px; border-radius: 9px; background: #dc2626; color: #fff; font-size: 11px; line-height: 1; }
</style>
