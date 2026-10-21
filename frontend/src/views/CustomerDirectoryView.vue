<script setup lang="ts">
import { ref } from 'vue'
import { createCustomer, searchCustomers } from '../api/customers'
import type { Customer } from '../types/domain'
import Notice from '../components/Notice.vue'
import { safeError } from '../utils/errors'
const query=ref(''),rows=ref<Customer[]>([]),loading=ref(false),error=ref(''),showCreate=ref(false),name=ref(''),feedback=ref('')
async function search(){if(!query.value.trim())return;loading.value=true;error.value='';try{rows.value=(await searchCustomers(query.value.trim())).results}catch(e){error.value=safeError(e)}finally{loading.value=false}}
async function create(){if(!name.value.trim())return;loading.value=true;error.value='';try{const item=await createCustomer({name:name.value.trim()});feedback.value=`客户已创建：${item.name}`;query.value=item.name;showCreate.value=false;name.value='';await search()}catch(e){error.value=safeError(e)}finally{loading.value=false}}
</script>
<template><div class="page-heading"><div><p class="eyebrow">CUSTOMERS</p><h1>客户</h1><p class="muted">搜索共享客户资料，或为新商机建立客户。</p></div><el-button type="primary" @click="showCreate=!showCreate">新建客户</el-button></div><Notice :error="error" :loading="loading"/><p v-if="feedback" class="notice">{{ feedback }}</p><section v-if="showCreate" class="panel action-form"><h2>新建客户</h2><label>客户名称</label><input v-model="name"><el-button type="primary" :disabled="!name.trim()" @click="create">保存</el-button></section><section class="panel"><div class="row"><input v-model="query" placeholder="输入客户名称" @keyup.enter="search"><el-button :loading="loading" @click="search">搜索</el-button></div><div v-if="!error&&rows.length" class="opportunity-list"><div v-for="item in rows" :key="item.id" class="opportunity-row"><strong>{{ item.name }}</strong><small>{{ item.industry||'行业未填写' }} · {{ item.company_size||'规模未填写' }}</small></div></div><p v-else-if="!error&&query&&!loading" class="empty">未找到匹配客户。</p><p v-else-if="!error" class="empty">输入客户名称开始搜索。</p></section></template>
