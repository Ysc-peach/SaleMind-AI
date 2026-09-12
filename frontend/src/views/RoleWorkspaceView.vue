<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '../stores/auth'
import SalesWorkspace from './SalesWorkspaceView.vue'
import PresalesWorkspace from './PresalesWorkspaceView.vue'
const auth=useAuthStore()
const component=computed(()=>auth.user?.role==='sales'?SalesWorkspace:auth.user?.role==='presales'?PresalesWorkspace:null)
</script>
<template><component :is="component" v-if="component"/><section v-else class="panel"><p class="eyebrow">ADMIN WORKSPACE</p><h1>业务管理入口</h1><p class="muted">查看全部商机并处理需要业务管理员兜底的事项。</p><RouterLink to="/opportunities" class="action-link">进入商机列表</RouterLink></section></template>
