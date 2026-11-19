<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  createFollowUp,
  listFollowUps,
  setFollowUpDone,
} from '../api/follow-ups'
import type { FollowUpTask } from '../types/domain'
import { safeError } from '../utils/errors'

const props = defineProps<{ opportunityId: number; readOnly?: boolean }>()
const canWrite = computed(() => !props.readOnly)
const rows = ref<FollowUpTask[]>([])
const loading = ref(false)
const error = ref('')
const feedback = ref('')
const busyId = ref<number | null>(null)
const title = ref('')
const dueOn = ref(new Date().toISOString().slice(0, 10))
const showDone = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await listFollowUps(
      props.opportunityId,
      showDone.value ? 'all' : 'open',
    )
    rows.value = data.results
  } catch (e) {
    error.value = safeError(e)
  } finally {
    loading.value = false
  }
}

async function add() {
  const text = title.value.trim()
  if (!text || !dueOn.value) return
  loading.value = true
  error.value = ''
  try {
    await createFollowUp(props.opportunityId, { title: text, due_on: dueOn.value })
    title.value = ''
    feedback.value = '已添加跟进事项'
    await load()
  } catch (e) {
    error.value = safeError(e)
  } finally {
    loading.value = false
  }
}

async function toggle(row: FollowUpTask) {
  busyId.value = row.id
  error.value = ''
  try {
    await setFollowUpDone(row.id, row.status === 'open')
    feedback.value = row.status === 'open' ? '已标记完成' : '已重新打开'
    await load()
  } catch (e) {
    error.value = safeError(e)
  } finally {
    busyId.value = null
  }
}

onMounted(load)
</script>
<template>
  <section class="panel">
    <h2>跟进事项</h2>
    <p class="muted">到期日用于提醒；归档的商机不再接收新的跟进。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="feedback" role="status">{{ feedback }}</p>
    <div v-if="canWrite" class="row">
      <input v-model="title" data-test="follow-up-title" placeholder="要做什么（例如：回访客户确认 POC 时间）" />
      <input v-model="dueOn" data-test="follow-up-due" type="date" />
      <el-button type="primary" :loading="loading" data-test="follow-up-add" @click="add">添加</el-button>
      <el-checkbox v-model="showDone" data-test="follow-up-show-done" @change="load">含已完成</el-checkbox>
    </div>
    <p v-if="!rows.length && !loading" class="muted">暂无待办。</p>
    <ul v-else class="follow-up-list">
      <li v-for="row in rows" :key="row.id" :data-test="`follow-up-${row.id}`">
        <strong>{{ row.title }}</strong>
        <small>到期 {{ row.due_on }} · {{ row.owner_name }}</small>
        <el-tag v-if="row.is_overdue" type="danger" size="small" data-test="follow-up-overdue">已逾期</el-tag>
        <el-tag v-else-if="row.status === 'done'" type="info" size="small">已完成</el-tag>
        <el-button
          v-if="canWrite"
          text
          :loading="busyId === row.id"
          :data-test="`follow-up-toggle-${row.id}`"
          @click="toggle(row)"
        >{{ row.status === 'open' ? '完成' : '恢复' }}</el-button>
      </li>
    </ul>
  </section>
</template>
