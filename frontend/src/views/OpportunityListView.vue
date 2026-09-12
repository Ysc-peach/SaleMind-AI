<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { listOpportunities } from '../api/opportunities'
import type { Opportunity } from '../types/domain'
import { safeError } from '../utils/errors'
import { label } from '../utils/labels'
import Notice from '../components/Notice.vue'
const rows = ref<Opportunity[]>([]), page = ref(1), total = ref(0), loading = ref(false), error = ref('')
async function load() {
  loading.value = true; error.value = ''; rows.value = []
  try { const data = await listOpportunities(page.value); rows.value = data.results; total.value = data.count }
  catch (e) { error.value = safeError(e) } finally { loading.value = false }
}
onMounted(load)
</script>
<template><div class="page-heading"><div><p class="eyebrow">OPPORTUNITIES</p><h1>商机工作台</h1><p class="muted">从客户需求到可交付技术方案，在同一处推进。</p></div><el-button :loading="loading" @click="load">刷新</el-button></div>
<Notice :error="error" :loading="loading" />
<section v-if="!loading && !error" class="panel"><el-table :data="rows" empty-text="暂无可访问的商机，请由销售负责人创建或指派商机。"><el-table-column label="项目名称" min-width="200"><template #default="{ row }"><RouterLink :to="`/opportunities/${row.id}`">{{ row.project_name }}</RouterLink></template></el-table-column><el-table-column label="客户"><template #default="{ row }">{{ row.customer_name || '客户名称未提供' }}</template></el-table-column><el-table-column label="阶段"><template #default="{ row }">{{ label(row.stage) }}</template></el-table-column><el-table-column label="状态"><template #default="{ row }"><el-tag>{{ label(row.status) }}</el-tag></template></el-table-column><el-table-column label="销售负责人"><template #default="{ row }">{{ row.sales_owner_name || '—' }}</template></el-table-column><el-table-column label="售前负责人"><template #default="{ row }">{{ row.presales_owner_name || '未指派' }}</template></el-table-column></el-table>
<el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load" /></section></template>
