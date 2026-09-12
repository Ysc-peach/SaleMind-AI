<script setup lang="ts">
import { useAuthStore } from '../stores/auth'
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { label } from '../utils/labels'
const auth = useAuthStore(), router = useRouter()
const nav = computed(() => auth.user?.role === 'sales' ? [
  {to:'/workspace',label:'工作台'}, {to:'/opportunities',label:'商机'}, {to:'/customers',label:'客户'},
] : auth.user?.role === 'presales' ? [
  {to:'/workspace',label:'工作台'}, {to:'/reviews',label:'待审核'}, {to:'/opportunities',label:'商机'},
] : [{to:'/workspace',label:'工作台'},{to:'/opportunities',label:'商机'}])
function logout() { auth.logout(); router.replace('/login') }
</script>
<template><div class="app-shell"><aside class="app-sidebar"><RouterLink to="/workspace" class="brand">S<span>SalesMind AI</span></RouterLink><p class="nav-caption">售前协作</p><nav class="side-nav"><RouterLink v-for="item in nav" :key="item.to" :to="item.to" class="nav-item">{{ item.label }}</RouterLink></nav><div class="sidebar-note">需求有依据<br>方案可追溯<br>审核留记录</div></aside><div class="app-body"><header><span>企业智能售前与解决方案助手</span><div>{{ auth.user?.first_name || auth.user?.username }} <el-tag size="small">{{ label(auth.user?.role ?? '') }}</el-tag><el-button text @click="logout">退出登录</el-button></div></header><main class="content"><RouterView :key="$route.path" /></main></div></div></template>
