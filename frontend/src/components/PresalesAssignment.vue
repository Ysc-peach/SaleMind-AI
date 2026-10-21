<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { getOpportunity, savePresalesOwner } from '../api/opportunities'
import { listPresalesOptions } from '../api/users'
import type { Opportunity, PresalesOption } from '../types/domain'
import { safeError } from '../utils/errors'
import Notice from './Notice.vue'

const props = defineProps<{ opportunity: Opportunity }>()
const emit = defineEmits<{ updated: [opportunity: Opportunity] }>()
const editing = ref(false), loading = ref(false), saving = ref(false), ready = ref(false)
const selected = ref(''), options = ref<PresalesOption[]>([])
const error = ref(''), saved = ref(false)
const needsRefresh = ref(false)
let request = 0, active = true
onBeforeUnmount(() => { active = false; request++ })
const missingOwner = computed(() => props.opportunity.presales_owner !== null && !options.value.some(p => p.id === props.opportunity.presales_owner))
const selectedId = computed(() => selected.value === '' ? null : Number(selected.value))
const canSave = computed(() => ready.value && !loading.value && !saving.value
  && selectedId.value !== props.opportunity.presales_owner
  && (selectedId.value === null || options.value.some(p => p.id === selectedId.value)))
function personName(person: PresalesOption) {
  const name = `${person.last_name}${person.first_name}`.trim()
  return name ? `${name}（${person.username}）` : person.username
}
async function open() {
  if (saving.value || needsRefresh.value) return
  const current = ++request
  editing.value = true; selected.value = props.opportunity.presales_owner === null ? '' : String(props.opportunity.presales_owner)
  saved.value = false; error.value = ''; ready.value = false; loading.value = true; options.value = []
  try {
    const people = await listPresalesOptions()
    if (active && current === request) { options.value = people; ready.value = true }
  } catch (e) {
    if (active && current === request) error.value = safeError(e)
  } finally {
    if (active && current === request) loading.value = false
  }
}
function cancel() {
  if (saving.value) return
  request++; editing.value = false; error.value = ''; loading.value = false
}
async function save() {
  if (!canSave.value) return
  const id = props.opportunity.id
  saving.value = true; saved.value = false; error.value = ''
  try {
    await savePresalesOwner(id, selectedId.value)
    if (!active) return
    // PATCH uses the update serializer, which has no id or display names.
    // Read the authoritative detail instead of assuming a detail-shaped response.
    try {
      const updated = await getOpportunity(id)
      if (active) { emit('updated', updated); editing.value = false; saved.value = true }
    } catch {
      if (active) {
        editing.value = false
        needsRefresh.value = true
        error.value = '指派已保存，但未能刷新负责人信息。请刷新商机页面核对结果，勿重复保存。'
      }
    }
  } catch (e) {
    if (active) {
      const status = (e as { response?: { status?: number } })?.response?.status
      error.value = status ? safeError(e) : '请求未完成，尚未确认是否保存。请刷新商机页面核对售前负责人，勿重复保存。'
      if (!status) { needsRefresh.value = true; editing.value = false }
    }
  } finally {
    if (active) saving.value = false
  }
}
async function refreshOwner() {
  if (!needsRefresh.value || loading.value || saving.value) return
  loading.value = true
  try {
    const updated = await getOpportunity(props.opportunity.id)
    if (active) { emit('updated', updated); needsRefresh.value = false; error.value = '' }
  } catch {
    if (active) error.value = '未能刷新负责人信息。请稍后刷新商机页面核对结果，勿重复保存。'
  } finally {
    if (active) loading.value = false
  }
}
</script>

<template>
  <div class="presales-assignment">
    <el-button v-if="!editing" :disabled="needsRefresh" @click="open">{{ opportunity.presales_owner === null ? '指派售前' : '更换售前' }}</el-button>
    <Notice :error="error" :loading="loading" />
    <el-button v-if="needsRefresh" :loading="loading" :disabled="loading" @click="refreshOwner">刷新售前负责人</el-button>
    <form v-if="editing" @submit.prevent="save">
      <label for="presales-owner">选择售前负责人</label>
      <select id="presales-owner" v-model="selected" :disabled="loading || saving || !ready">
        <option value="">暂不指派（清空负责人）</option>
        <option v-if="missingOwner" :value="String(opportunity.presales_owner)" disabled>{{ opportunity.presales_owner_name || '当前负责人' }}（当前不可选）</option>
        <option v-for="person in options" :key="person.id" :value="String(person.id)">{{ personName(person) }}</option>
      </select>
      <p v-if="ready && !options.length" class="muted">暂无可指派的在职售前，请联系管理员维护售前账号。</p>
      <p class="muted">仅本商机的销售负责人可调整指派。更换负责人不会自动提交或批准方案，也不会改派已提交版本的审核人。</p>
      <div class="assignment-actions">
        <el-button type="primary" native-type="submit" :loading="saving" :disabled="!canSave">保存售前指派</el-button>
        <el-button :disabled="saving" @click="cancel">取消</el-button>
        <el-button v-if="!ready && !loading" @click="open">重新加载售前列表</el-button>
      </div>
    </form>
    <p v-if="saved" role="status">售前指派已保存。</p>
  </div>
</template>

<style scoped>
.presales-assignment { margin-top: 1.5rem; }
select { max-width: 32rem; }
.assignment-actions { display: flex; flex-wrap: wrap; gap: .75rem; }
.assignment-actions .el-button { margin-left: 0; }
</style>
