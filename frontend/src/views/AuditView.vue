<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { auditEvents, type AuditEvents } from '../api/audit'
import Notice from '../components/Notice.vue'
import { safeError } from '../utils/errors'
import { dateTime, label } from '../utils/labels'

const PAGE_SIZE = 20

const data = ref<AuditEvents | null>(null)
const loading = ref(false)
const error = ref('')
const page = ref(1)
const filters = reactive({ actor: '', status: '', date_from: '', date_to: '' })

const statusText: Record<string, string> = {
  PENDING: '待处理', APPROVED: '已通过', RETURNED: '已退回',
  QUEUED: '排队中', RUNNING: '生成中', SUCCEEDED: '已成功', FAILED: '已失败',
}
const statusOptions = [
  { value: '', label: '全部状态' },
  { value: 'PENDING', label: '待处理' },
  { value: 'APPROVED', label: '已通过' },
  { value: 'RETURNED', label: '已退回' },
  { value: 'QUEUED', label: '排队中' },
  { value: 'RUNNING', label: '生成中' },
  { value: 'SUCCEEDED', label: '已成功' },
  { value: 'FAILED', label: '已失败' },
]
const showStatus = (value: string) => statusText[value] ?? value
const showReason = (value: string) => (value ? label(value) : '')

async function load() {
  loading.value = true; error.value = ''
  try { data.value = await auditEvents({ ...filters }, page.value, PAGE_SIZE) }
  catch (e) { error.value = safeError(e) }
  finally { loading.value = false }
}

function search() {
  page.value = 1
  void load()
}

function reset() {
  filters.actor = ''; filters.status = ''
  filters.date_from = ''; filters.date_to = ''
  search()
}

const hasNext = computed(() => {
  if (!data.value) return false
  const reached = page.value * PAGE_SIZE
  return (
    reached < data.value.reviews.count || reached < data.value.generations.count
  )
})

function go(delta: number) {
  const next = page.value + delta
  if (next < 1 || (delta > 0 && !hasNext.value)) return
  page.value = next
  void load()
}

onMounted(load)
</script>
<template>
  <div class="page-heading">
    <div>
      <p class="eyebrow">AUDIT</p>
      <h1>审计</h1>
      <p class="muted">只读视图：谁提交了审核、谁审核、谁发起了方案生成，以及每条的结果。</p>
    </div>
  </div>
  <Notice :error="error" :loading="loading" />
  <section class="panel audit-filters">
    <label>操作人<input v-model="filters.actor" data-test="filter-actor" placeholder="用户名或姓名片段" @keyup.enter="search"></label>
    <label>状态
      <select v-model="filters.status" data-test="filter-status">
        <option v-for="option in statusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
      </select>
    </label>
    <label>起始日期<input v-model="filters.date_from" data-test="filter-from" type="date"></label>
    <label>结束日期<input v-model="filters.date_to" data-test="filter-to" type="date"></label>
    <div class="row">
      <el-button :loading="loading" data-test="audit-search" @click="search">查询</el-button>
      <el-button text data-test="audit-reset" @click="reset">重置</el-button>
    </div>
  </section>
  <section class="panel" data-test="audit-reviews">
    <h2>审核记录<span v-if="data" class="muted">（共 {{ data.reviews.count }} 条）</span></h2>
    <p v-if="data && !data.reviews.count" class="empty">没有符合条件的审核记录。</p>
    <table v-else-if="data" class="audit-table">
      <thead>
        <tr><th>商机</th><th>提交人</th><th>审核人</th><th>状态</th><th>提交时间</th><th>决定时间</th></tr>
      </thead>
      <tbody>
        <tr v-for="item in data.reviews.results" :key="`review-${item.id}`" :data-test="`review-${item.id}`">
          <td><RouterLink :to="`/opportunities/${item.opportunity_id}`">{{ item.project_name }}</RouterLink></td>
          <td>{{ item.submitted_by }}</td>
          <td>{{ item.reviewer }}</td>
          <td>{{ showStatus(item.status) }}<small v-if="item.return_reason"> · {{ showReason(item.return_reason) }}</small></td>
          <td>{{ dateTime(item.submitted_at) }}</td>
          <td>{{ item.decided_at ? dateTime(item.decided_at) : '待处理' }}</td>
        </tr>
      </tbody>
    </table>
  </section>
  <section class="panel" data-test="audit-generations">
    <h2>生成任务<span v-if="data" class="muted">（共 {{ data.generations.count }} 条）</span></h2>
    <p v-if="data && !data.generations.count" class="empty">没有符合条件的生成任务。</p>
    <table v-else-if="data" class="audit-table">
      <thead>
        <tr><th>商机</th><th>发起人</th><th>状态</th><th>错误代码</th><th>创建时间</th><th>结束时间</th></tr>
      </thead>
      <tbody>
        <tr v-for="item in data.generations.results" :key="`generation-${item.id}`">
          <td><RouterLink :to="`/opportunities/${item.opportunity_id}`">{{ item.project_name }}</RouterLink></td>
          <td>{{ item.requested_by }}</td>
          <td>{{ showStatus(item.status) }}</td>
          <td>{{ item.error_code || '—' }}</td>
          <td>{{ dateTime(item.created_at) }}</td>
          <td>{{ item.finished_at ? dateTime(item.finished_at) : '进行中' }}</td>
        </tr>
      </tbody>
    </table>
  </section>
  <div class="row audit-pager">
    <el-button :disabled="page <= 1 || loading" data-test="audit-prev" @click="go(-1)">上一页</el-button>
    <span class="muted" data-test="audit-page">第 {{ page }} 页</span>
    <el-button :disabled="!hasNext || loading" data-test="audit-next" @click="go(1)">下一页</el-button>
  </div>
</template>
<style scoped>
.audit-filters { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
.audit-filters label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: #475569; }
.audit-filters input, .audit-filters select { padding: 6px 8px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 13px; min-width: 140px; }
.audit-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.audit-table th, .audit-table td { padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: left; }
.audit-table th { color: #64748b; font-weight: 600; }
.audit-pager { display: flex; align-items: center; gap: 12px; margin: 12px 0 24px; }
</style>
