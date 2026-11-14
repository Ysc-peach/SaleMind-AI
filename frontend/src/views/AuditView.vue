<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { auditEvents, type AuditEvents } from '../api/audit'
import Notice from '../components/Notice.vue'
import { safeError } from '../utils/errors'
import { dateTime, label } from '../utils/labels'

const data = ref<AuditEvents | null>(null)
const loading = ref(false)
const error = ref('')
const statusText: Record<string, string> = {
  PENDING: '待处理', APPROVED: '已通过', RETURNED: '已退回',
  QUEUED: '排队中', RUNNING: '生成中', SUCCEEDED: '已成功', FAILED: '已失败',
}
const showStatus = (value: string) => statusText[value] ?? value
const showReason = (value: string) => (value ? label(value) : '')

async function load() {
  loading.value = true; error.value = ''
  try { data.value = await auditEvents() }
  catch (e) { error.value = safeError(e) }
  finally { loading.value = false }
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
  <section class="panel" data-test="audit-reviews">
    <h2>审核记录</h2>
    <p v-if="data && !data.reviews.length" class="empty">还没有审核记录。</p>
    <table v-else-if="data" class="audit-table">
      <thead>
        <tr><th>商机</th><th>提交人</th><th>审核人</th><th>状态</th><th>提交时间</th><th>决定时间</th></tr>
      </thead>
      <tbody>
        <tr v-for="item in data.reviews" :key="`review-${item.id}`" :data-test="`review-${item.id}`">
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
    <h2>生成任务</h2>
    <p v-if="data && !data.generations.length" class="empty">还没有生成任务。</p>
    <table v-else-if="data" class="audit-table">
      <thead>
        <tr><th>商机</th><th>发起人</th><th>状态</th><th>错误代码</th><th>创建时间</th><th>结束时间</th></tr>
      </thead>
      <tbody>
        <tr v-for="item in data.generations" :key="`generation-${item.id}`">
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
</template>
<style scoped>
.audit-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.audit-table th, .audit-table td { padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: left; }
.audit-table th { color: #64748b; font-weight: 600; }
</style>
