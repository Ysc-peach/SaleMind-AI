<script setup lang="ts">
import { useAuthStore } from '../stores/auth'
import { useRouter } from 'vue-router'
import { label } from '../utils/labels'
const auth = useAuthStore(), router = useRouter()
function logout() { auth.logout(); router.replace('/login') }
</script>
<template><div class="app-shell"><aside><RouterLink to="/opportunities" class="brand">S<span>SalesMind AI</span></RouterLink><p class="nav-caption">售前协作</p><RouterLink to="/opportunities" class="nav-item">▦ 商机工作台</RouterLink><div class="sidebar-note">需求有依据<br>方案可追溯<br>审核留记录</div></aside><div class="app-body"><header><span>企业智能售前与解决方案助手</span><div>{{ auth.user?.first_name || auth.user?.username }} <el-tag size="small">{{ label(auth.user?.role ?? '') }}</el-tag><el-button text @click="logout">退出登录</el-button></div></header><main class="content"><RouterView :key="$route.path" /></main></div></div></template>
