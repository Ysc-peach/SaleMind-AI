<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { listOpportunities, setOpportunityActive } from '../api/opportunities'
import type { Opportunity } from '../types/domain'
import { safeError } from '../utils/errors'
import { label } from '../utils/labels'
import Notice from '../components/Notice.vue'
import { useAuthStore } from '../stores/auth'
const auth = useAuthStore()
// Only an administrator may archive a record; the server enforces it too.
const isAdmin = computed(() => auth.user?.role === 'admin')
const rows = ref<Opportunity[]>([]), page = ref(1), total = ref(0), loading = ref(false), error = ref('')
const showInactive = ref(false), feedback = ref(''), busyId = ref<number | null>(null)
async function load() {
  loading.value = true; error.value = ''; rows.value = []
  try {
    const data = await listOpportunities(page.value, isAdmin.value && showInactive.value)
    rows.value = data.results; total.value = data.count
  }
  catch (e) { error.value = safeError(e) } finally { loading.value = false }
}
async function toggleActive(row: Opportunity) {
  busyId.value = row.id; error.value = ''
  try {
    await setOpportunityActive(row.id, !row.is_active)
    feedback.value = row.is_active ? `商机已停用：${row.project_name}` : `商机已恢复：${row.project_name}`
    await load()
  } catch (e) { error.value = safeError(e) } finally { busyId.value = null }
}
onMounted(load)
</script>
<template><div class="page-heading"><div><p class="eyebrow">OPPORTUNITIES</p><h1>商机工作台</h1><p class="muted">从客户需求到可交付技术方案，在同一处推进。</p></div><div class="row"><el-checkbox v-if="isAdmin" v-model="showInactive" data-test="show-inactive" @change="load">含已停用</el-checkbox><el-button :loading="loading" @click="load">刷新</el-button></div></div>
<Notice :error="error" :loading="loading" />
<p v-if="feedback" class="notice" role="status">{{ feedback }}</p>
<section v-if="!loading && !error" class="panel"><el-table :data="rows" empty-text="暂无可访问的商机，请由销售负责人创建或指派商机。"><el-table-column label="项目名称" min-width="200"><template #default="{ row }"><RouterLink :to="`/opportunities/${row.id}`">{{ row.project_name }}</RouterLink> <el-tag v-if="!row.is_active" type="info" size="small" data-test="inactive-tag">已停用</el-tag></template></el-table-column><el-table-column label="客户"><template #default="{ row }">{{ row.customer_name || '客户名称未提供' }}</template></el-table-column><el-table-column label="阶段"><template #default="{ row }">{{ label(row.stage) }}</template></el-table-column><el-table-column label="状态"><template #default="{ row }"><el-tag>{{ label(row.status) }}</el-tag></template></el-table-column><el-table-column label="销售负责人"><template #default="{ row }">{{ row.sales_owner_name || '—' }}</template></el-table-column><el-table-column label="售前负责人"><template #default="{ row }">{{ row.presales_owner_name || '未指派' }}</template></el-table-column><el-table-column v-if="isAdmin" label="操作" width="96"><template #default="{ row }"><el-button text :loading="busyId===row.id" :data-test="`toggle-${row.id}`" @click="toggleActive(row)">{{ row.is_active?'停用':'恢复' }}</el-button></template></el-table-column></el-table>
<el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load" /></section></template>
