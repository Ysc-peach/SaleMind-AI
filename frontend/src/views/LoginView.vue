<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { safeError } from '../utils/errors'
const username = ref(''), password = ref(''), busy = ref(false), error = ref('')
const auth = useAuthStore(), router = useRouter(), route = useRoute()
async function login() {
  if(busy.value) return
  busy.value = true; error.value = ''
  try { await auth.login(username.value, password.value); const next = String(route.query.next ?? ''); await router.replace(next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/login') ? next : '/workspace') }
  catch(e) { error.value = safeError(e) } finally { password.value = ''; busy.value = false }
}
</script>
<template><main class="login"><section class="login-intro"><div class="brand">S<span>SalesMind AI</span></div><p class="eyebrow">INTELLIGENT PRESALES</p><h1>让每一份方案，<br>都有据可循。</h1><p>连接客户需求、企业知识与技术审核，<br>让销售与售前在同一条业务链路上协作。</p><div class="login-steps">需求洞察 <span>→</span> 可信方案 <span>→</span> 技术审核</div></section><section class="login-form"><h2>登录工作台</h2><p class="muted">使用您的 SalesMind 业务账号</p><form @submit.prevent="login"><label for="username">用户名</label><input id="username" v-model="username" autocomplete="username" required :disabled="busy"><label for="password">密码</label><input id="password" v-model="password" type="password" autocomplete="current-password" required :disabled="busy"><p v-if="error" class="notice error" role="alert">{{ error }}</p><el-button type="primary" native-type="submit" :loading="busy">登录</el-button></form></section></main></template>
