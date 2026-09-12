<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createCustomer, searchCustomers } from '../api/customers'
import { createOpportunity } from '../api/opportunities'
import { listPresalesOptions } from '../api/users'
import { getSalesWorkspace } from '../api/workspaces'
import Notice from '../components/Notice.vue'
import type { Customer, PresalesOption } from '../types/domain'
import type { SalesWorkspace } from '../types/workspace'
import { safeError } from '../utils/errors'

const router=useRouter()
const data=ref<SalesWorkspace>(), loading=ref(false), error=ref(''), feedback=ref('')
const showCustomer=ref(false), showOpportunity=ref(false), saving=ref(false)
const customerForm=reactive({name:'',industry:'',company_size:'',basic_info:''})
const opportunityForm=reactive({project_name:'',customer:0,presales_owner:null as number|null,raw_requirement:'',budget:''})
const customerQuery=ref(''), customers=ref<Customer[]>([]), presales=ref<PresalesOption[]>([]), searchBusy=ref(false)

async function load(){loading.value=true;error.value='';try{data.value=await getSalesWorkspace()}catch(e){error.value=safeError(e)}finally{loading.value=false}}
async function saveCustomer(){if(saving.value||!customerForm.name.trim())return;saving.value=true;error.value='';try{const created=await createCustomer({...customerForm,name:customerForm.name.trim()});feedback.value=`客户已创建：${created.name}`;showCustomer.value=false;Object.assign(customerForm,{name:'',industry:'',company_size:'',basic_info:''})}catch(e){error.value=safeError(e)}finally{saving.value=false}}
async function openOpportunity(){showOpportunity.value=true;error.value='';try{presales.value=await listPresalesOptions()}catch(e){error.value=safeError(e)}}
async function findCustomers(){if(!customerQuery.value.trim())return;searchBusy.value=true;error.value='';try{customers.value=(await searchCustomers(customerQuery.value.trim())).results}catch(e){error.value=safeError(e)}finally{searchBusy.value=false}}
async function saveOpportunity(){if(saving.value||!opportunityForm.project_name.trim()||!opportunityForm.customer)return;saving.value=true;error.value='';try{const created=await createOpportunity({project_name:opportunityForm.project_name.trim(),customer:opportunityForm.customer,presales_owner:opportunityForm.presales_owner,raw_requirement:opportunityForm.raw_requirement,budget:opportunityForm.budget||null});await router.push(`/opportunities/${created.id}`)}catch(e){error.value=safeError(e)}finally{saving.value=false}}
onMounted(load)
</script>

<template>
  <div class="page-heading"><div><p class="eyebrow">SALES WORKSPACE</p><h1>销售工作台</h1><p class="muted">聚焦需要推进的客户信息、方案提交与商机。</p></div><div class="row"><el-button data-test="new-customer" @click="showCustomer=!showCustomer">新建客户</el-button><el-button data-test="new-opportunity" type="primary" @click="openOpportunity">新建商机</el-button></div></div>
  <Notice :error="error" :loading="loading" />
  <p v-if="feedback" class="notice" role="status">{{ feedback }}</p>

  <section v-if="showCustomer" class="panel action-form"><h2>新建客户</h2><label>客户名称</label><input data-test="customer-name" v-model="customerForm.name"><label>行业</label><input v-model="customerForm.industry"><label>公司规模</label><input v-model="customerForm.company_size"><label>基本信息</label><textarea v-model="customerForm.basic_info" rows="3"/><div class="row"><el-button @click="showCustomer=false">取消</el-button><el-button data-test="save-customer" type="primary" :loading="saving" :disabled="!customerForm.name.trim()" @click="saveCustomer">保存客户</el-button></div></section>

  <section v-if="showOpportunity" class="panel action-form"><h2>新建商机</h2><label>搜索客户</label><div class="row"><input data-test="customer-query" v-model="customerQuery" @keyup.enter="findCustomers"><el-button data-test="search-customer" :loading="searchBusy" @click="findCustomers">搜索</el-button></div><label>选择客户</label><select data-test="customer-select" v-model.number="opportunityForm.customer"><option :value="0">请选择</option><option v-for="item in customers" :key="item.id" :value="item.id">{{ item.name }}</option></select><label>项目名称</label><input data-test="project-name" v-model="opportunityForm.project_name"><label>售前负责人</label><select v-model="opportunityForm.presales_owner"><option :value="null">暂不指派</option><option v-for="item in presales" :key="item.id" :value="item.id">{{ [item.first_name,item.last_name].filter(Boolean).join(' ')||item.username }}</option></select><label>客户原始需求</label><textarea v-model="opportunityForm.raw_requirement" rows="4"/><div class="row"><el-button @click="showOpportunity=false">取消</el-button><el-button data-test="save-opportunity" type="primary" :loading="saving" :disabled="!opportunityForm.project_name.trim()||!opportunityForm.customer" @click="saveOpportunity">创建并进入商机</el-button></div></section>

  <template v-if="data && !loading">
    <div class="task-grid">
      <section class="task-card"><h2>待补充客户信息 <span>{{ data.tasks.customer_info_required.length }}</span></h2><RouterLink v-for="item in data.tasks.customer_info_required" :key="item.solution_draft_id" :to="`/opportunities/${item.opportunity_id}?tab=requirement`" class="task-row"><strong>{{ item.project_name }}</strong><small>{{ item.customer_name }} · 需要补充客户信息</small></RouterLink></section>
      <section class="task-card"><h2>待提交售前审核 <span>{{ data.tasks.waiting_for_sales_confirmation.length }}</span></h2><RouterLink v-for="item in data.tasks.waiting_for_sales_confirmation" :key="item.solution_draft_id" :to="`/solutions/${item.solution_draft_id}`" class="task-row"><strong>{{ item.project_name }} · V{{ item.solution_version }}</strong><small>{{ item.customer_name }} · 查看草稿并提交</small></RouterLink></section>
      <section class="task-card"><h2>等待售前审核 <span>{{ data.tasks.waiting_for_presales_review.length }}</span></h2><RouterLink v-for="item in data.tasks.waiting_for_presales_review" :key="item.solution_draft_id" :to="`/solutions/${item.solution_draft_id}`" class="task-row"><strong>{{ item.project_name }} · V{{ item.solution_version }}</strong><small>{{ item.customer_name }} · 等待售前审核</small></RouterLink></section>
    </div>
    <p v-if="!data.my_opportunities.length && !data.tasks.customer_info_required.length && !data.tasks.waiting_for_sales_confirmation.length && !data.tasks.waiting_for_presales_review.length" class="panel empty">目前没有待办。可以新建客户或商机开始推进。</p>
    <section v-else class="panel"><div class="section-heading"><h2>我的商机</h2><RouterLink to="/opportunities">查看全部</RouterLink></div><div class="opportunity-list"><RouterLink v-for="item in data.my_opportunities" :key="item.id" :to="`/opportunities/${item.id}`" class="opportunity-row"><span><strong>{{ item.project_name }}</strong><small>{{ item.customer_name||'客户名称未提供' }}</small></span><span>{{ item.sales_owner_name||'—' }} · {{ item.presales_owner_name||'未指派售前' }}</span></RouterLink></div></section>
    <section v-if="data.recently_updated.length" class="panel"><h2>最近更新</h2><div class="opportunity-list"><RouterLink v-for="item in data.recently_updated" :key="item.id" :to="`/opportunities/${item.id}`" class="opportunity-row"><strong>{{ item.project_name }}</strong><small>{{ item.customer_name||'—' }}</small></RouterLink></div></section>
  </template>
</template>
