<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter, onBeforeRouteLeave } from 'vue-router'
import { getOpportunity, saveRequirement } from '../api/opportunities'
import { useAuthStore } from '../stores/auth'
import type { Opportunity } from '../types/domain'
import { safeError } from '../utils/errors'
import { label } from '../utils/labels'
import Notice from '../components/Notice.vue'
import AnalysisPanel from '../components/AnalysisPanel.vue'
import SolutionList from '../components/SolutionList.vue'
const route = useRoute(), router = useRouter(), auth = useAuthStore()
const record = ref<Opportunity>(), requirement = ref(''), loading = ref(false), saving = ref(false), error = ref(''), saved = ref(false)
const tabs = [{key:'overview', name:'概览'}, {key:'requirement', name:'客户需求'}, {key:'analysis', name:'AI需求分析'}, {key:'solutions', name:'技术方案'}, {key:'review', name:'审核'}]
const tab = computed(() => tabs.some(t => t.key === route.query.tab) ? String(route.query.tab) : 'overview')
const editable = computed(() => auth.user?.role === 'sales' && auth.user.id === record.value?.sales_owner)
const dirty = computed(() => editable.value && requirement.value !== (record.value?.raw_requirement ?? ''))
let request = 0
async function load() {
  const current = ++request; record.value = undefined; loading.value = true; error.value = ''; saved.value = false
  try { const data = await getOpportunity(Number(route.params.id)); if(current === request) { record.value = data; requirement.value = data.raw_requirement ?? '' } }
  catch(e) { if(current === request) error.value = safeError(e) } finally { if(current === request) loading.value = false }
}
async function save() {
  if(saving.value || !record.value) return
  saving.value = true; error.value = ''; saved.value = false
  try { await saveRequirement(record.value.id, requirement.value); await load(); saved.value = true } catch(e) { error.value = safeError(e) } finally { saving.value = false }
}
onBeforeRouteLeave(() => !dirty.value || window.confirm('客户需求尚未保存，确认离开？'))
watch(() => route.params.id, load, { immediate: true })
</script>
<template><RouterLink to="/opportunities" class="back-link">← 商机列表</RouterLink><Notice :error="error" :loading="loading" />
<template v-if="record"><div class="page-heading"><div><p class="eyebrow">OPPORTUNITY</p><h1>{{ record.project_name }}</h1><p class="muted">{{ record.customer_name || '客户名称未提供' }} · {{ label(record.stage) }}</p></div><el-tag>{{ label(record.status) }}</el-tag></div>
<nav class="tabs" aria-label="商机工作区"><button v-for="item in tabs" :key="item.key" :class="{active: tab===item.key}" @click="router.replace({query:{tab:item.key}})">{{ item.name }}</button></nav>
<section v-if="tab === 'overview'" class="panel"><h2>商机概览</h2><dl class="facts"><div><dt>客户</dt><dd>{{ record.customer_name || '客户名称未提供' }}</dd></div><div><dt>销售负责人</dt><dd>{{ record.sales_owner_name || '—' }}</dd></div><div><dt>售前负责人</dt><dd>{{ record.presales_owner_name || '未指派' }}</dd></div><div><dt>预算</dt><dd>{{ record.budget ?? '未确认' }}</dd></div><div><dt>预计上线</dt><dd>{{ record.expected_launch_date ?? '未确认' }}</dd></div></dl></section>
<section v-if="tab === 'requirement'" class="panel"><h2>客户需求事实</h2><p class="muted">需求分析保留独立快照。更新事实后，请重新执行分析并生成新的方案版本。</p><template v-if="editable"><label for="raw-requirement">原始需求</label><textarea id="raw-requirement" v-model="requirement" rows="10" /><el-button type="primary" :loading="saving" :disabled="!dirty" @click="save">保存客户需求</el-button><p v-if="saved" role="status">客户需求已保存。</p></template><p v-else class="preserve">{{ record.raw_requirement || '暂无客户需求。' }}</p></section>
<AnalysisPanel v-if="tab==='analysis'" :opportunity-id="record.id" />
<SolutionList v-if="tab==='solutions'||tab==='review'" :key="tab" :opportunity-id="record.id" :review-mode="tab==='review'" />
</template></template>
