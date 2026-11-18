<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { createCustomer, searchCustomers, setCustomerActive, updateCustomer } from '../api/customers'
import type { Customer } from '../types/domain'
import Notice from '../components/Notice.vue'
import { safeError } from '../utils/errors'
import { useAuthStore } from '../stores/auth'
const auth=useAuthStore()
// Archiving is an administrator action; the server enforces it, the UI just
// does not offer it to anyone else.
const isAdmin=computed(()=>auth.user?.role==='admin')
const query=ref(''),rows=ref<Customer[]>([]),loading=ref(false),error=ref(''),showCreate=ref(false),name=ref(''),feedback=ref('')
const editing=ref<Customer|null>(null),editBusy=ref(false),showInactive=ref(false),busyId=ref<number|null>(null)
const editForm=reactive({name:'',industry:'',company_size:'',basic_info:''})
async function search(){if(!query.value.trim())return;loading.value=true;error.value='';try{rows.value=(await searchCustomers(query.value.trim(),1,isAdmin.value&&showInactive.value)).results}catch(e){error.value=safeError(e)}finally{loading.value=false}}
async function toggleActive(item:Customer){
  busyId.value=item.id;error.value=''
  try{
    await setCustomerActive(item.id,!item.is_active)
    feedback.value=item.is_active?`客户已停用：${item.name}`:`客户已恢复：${item.name}`
    await search()
  }catch(e){error.value=safeError(e)}finally{busyId.value=null}
}
async function create(){if(!name.value.trim())return;loading.value=true;error.value='';try{const item=await createCustomer({name:name.value.trim()});feedback.value=`客户已创建：${item.name}`;query.value=item.name;showCreate.value=false;name.value='';await search()}catch(e){error.value=safeError(e)}finally{loading.value=false}}
function openEdit(item:Customer){
  editing.value=item;error.value=''
  editForm.name=item.name;editForm.industry=item.industry
  editForm.company_size=item.company_size;editForm.basic_info=item.basic_info
}
function cancelEdit(){editing.value=null}
async function saveEdit(){
  if(!editing.value||!editForm.name.trim())return
  editBusy.value=true;error.value=''
  try{
    const item=await updateCustomer(editing.value.id,{
      name:editForm.name.trim(),industry:editForm.industry,
      company_size:editForm.company_size,basic_info:editForm.basic_info,
    })
    feedback.value=`客户资料已更新：${item.name}`
    editing.value=null
    await search()
  }catch(e){error.value=safeError(e)}finally{editBusy.value=false}
}
</script>
<template>
  <div class="page-heading">
    <div>
      <p class="eyebrow">CUSTOMERS</p>
      <h1>客户</h1>
      <p class="muted">搜索共享客户资料，或为新商机建立客户。</p>
    </div>
    <el-button type="primary" @click="showCreate=!showCreate">新建客户</el-button>
  </div>
  <Notice :error="error" :loading="loading" />
  <p v-if="feedback" class="notice" role="status">{{ feedback }}</p>
  <section v-if="showCreate" class="panel action-form">
    <h2>新建客户</h2>
    <label>客户名称</label>
    <input v-model="name">
    <el-button type="primary" :disabled="!name.trim()" @click="create">保存</el-button>
  </section>
  <section v-if="editing" class="panel action-form" data-test="customer-edit">
    <h2>编辑客户资料</h2>
    <p class="muted">客户资料是团队共享数据，任何销售都可以修正；创建人不会因此改变。</p>
    <label>客户名称</label>
    <input v-model="editForm.name" data-test="edit-name">
    <label>行业</label>
    <input v-model="editForm.industry" data-test="edit-industry">
    <label>公司规模</label>
    <input v-model="editForm.company_size" data-test="edit-size">
    <label>基本信息</label>
    <textarea v-model="editForm.basic_info" data-test="edit-info" rows="3" />
    <div class="row">
      <el-button :disabled="editBusy" @click="cancelEdit">取消</el-button>
      <el-button type="primary" :loading="editBusy" :disabled="!editForm.name.trim()" @click="saveEdit">保存修改</el-button>
    </div>
  </section>
  <section class="panel">
    <div class="row">
      <input v-model="query" placeholder="输入客户名称" @keyup.enter="search">
      <el-button :loading="loading" @click="search">搜索</el-button>
      <el-checkbox v-if="isAdmin" v-model="showInactive" data-test="show-inactive" @change="search">含已停用</el-checkbox>
    </div>
    <div v-if="!error&&rows.length" class="opportunity-list">
      <div v-for="item in rows" :key="item.id" class="opportunity-row">
        <strong>{{ item.name }}</strong>
        <el-tag v-if="!item.is_active" type="info" data-test="inactive-tag">已停用</el-tag>
        <small>{{ item.industry||'行业未填写' }} · {{ item.company_size||'规模未填写' }}</small>
        <el-button text :data-test="`edit-${item.id}`" :disabled="!item.is_active" @click="openEdit(item)">编辑</el-button>
        <el-button
          v-if="isAdmin"
          text
          :loading="busyId===item.id"
          :data-test="`toggle-${item.id}`"
          @click="toggleActive(item)"
        >{{ item.is_active?'停用':'恢复' }}</el-button>
      </div>
    </div>
    <p v-else-if="!error&&query&&!loading" class="empty">未找到匹配客户。</p>
    <p v-else-if="!error" class="empty">输入客户名称开始搜索。</p>
  </section>
</template>
