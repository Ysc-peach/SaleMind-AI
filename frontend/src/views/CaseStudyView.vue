<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  createCaseStudy,
  listCaseStudies,
  setCaseStudyActive,
  updateCaseStudy,
} from '../api/case-studies'
import type { CaseStudy } from '../types/domain'
import { safeError } from '../utils/errors'
import { label } from '../utils/labels'
import Notice from '../components/Notice.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
// The server refuses writes from anyone but presales and administrators; the
// UI just does not offer what would be rejected.
const canWrite = computed(
  () => auth.user?.role === 'presales' || auth.user?.role === 'admin',
)
const isAdmin = computed(() => auth.user?.role === 'admin')

const rows = ref<CaseStudy[]>([])
const count = ref(0)
const page = ref(1)
const loading = ref(false)
const error = ref('')
const feedback = ref('')
const busyId = ref<number | null>(null)

const filters = reactive({
  q: '',
  industry: '',
  size_band: '',
  referenceable: false,
  include_inactive: false,
})

const editing = ref<CaseStudy | null>(null)
const showForm = ref(false)
const saving = ref(false)
const form = reactive({
  title: '',
  industry: '',
  size_band: 'medium',
  customer_name: '',
  pain_points: '',
  approach: '',
  results: '',
  referenceable: false,
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await listCaseStudies(
      {
        q: filters.q.trim(),
        industry: filters.industry.trim(),
        size_band: filters.size_band,
        referenceable: filters.referenceable,
        include_inactive: isAdmin.value && filters.include_inactive,
      },
      page.value,
    )
    rows.value = data.results
    count.value = data.count
  } catch (e) {
    error.value = safeError(e)
  } finally {
    loading.value = false
  }
}

function reset() {
  filters.q = ''
  filters.industry = ''
  filters.size_band = ''
  filters.referenceable = false
  filters.include_inactive = false
  page.value = 1
  return load()
}

function openCreate() {
  editing.value = null
  Object.assign(form, {
    title: '', industry: '', size_band: 'medium', customer_name: '',
    pain_points: '', approach: '', results: '', referenceable: false,
  })
  showForm.value = true
}

function openEdit(row: CaseStudy) {
  editing.value = row
  Object.assign(form, {
    title: row.title,
    industry: row.industry,
    size_band: row.size_band,
    customer_name: row.customer_name,
    pain_points: row.pain_points,
    approach: row.approach,
    results: row.results,
    referenceable: row.referenceable,
  })
  showForm.value = true
}

async function save() {
  if (saving.value) return
  if (!form.title.trim() || !form.industry.trim()) {
    error.value = '案例名称与行业为必填项。'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const payload = {
      ...form,
      title: form.title.trim(),
      industry: form.industry.trim(),
    }
    if (editing.value) await updateCaseStudy(editing.value.id, payload)
    else await createCaseStudy(payload)
    feedback.value = editing.value ? '案例已更新。' : '案例已创建。'
    showForm.value = false
    await load()
  } catch (e) {
    error.value = safeError(e)
  } finally {
    saving.value = false
  }
}

async function toggle(row: CaseStudy) {
  busyId.value = row.id
  error.value = ''
  try {
    await setCaseStudyActive(row.id, !row.is_active)
    feedback.value = row.is_active ? `案例已停用：${row.title}` : `案例已恢复：${row.title}`
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
  <div class="page-heading">
    <div>
      <p class="eyebrow">CASE LIBRARY</p>
      <h1>案例库</h1>
      <p class="muted">按行业与客户规模查找可复用的交付案例；文档回答「事实」，案例回答「像谁」。</p>
    </div>
    <el-button v-if="canWrite" type="primary" data-test="case-new" @click="openCreate">新建案例</el-button>
  </div>
  <Notice :error="error" :loading="loading" />
  <p v-if="feedback" class="notice" role="status">{{ feedback }}</p>

  <section v-if="showForm" class="panel" data-test="case-form">
    <h2>{{ editing ? '编辑案例' : '新建案例' }}</h2>
    <div class="case-form">
      <label>案例名称<input v-model="form.title" data-test="case-title" placeholder="例如：制造业知识库一期" /></label>
      <label>行业<input v-model="form.industry" data-test="case-industry" placeholder="例如：manufacturing" /></label>
      <label>客户规模
        <select v-model="form.size_band" data-test="case-size">
          <option value="small">{{ label('small') }}</option>
          <option value="medium">{{ label('medium') }}</option>
          <option value="large">{{ label('large') }}</option>
        </select>
      </label>
      <label>客户名称（留空表示匿名）<input v-model="form.customer_name" data-test="case-customer" /></label>
    </div>
    <label>客户痛点<textarea v-model="form.pain_points" data-test="case-pain" rows="2" /></label>
    <label>我们的做法<textarea v-model="form.approach" data-test="case-approach" rows="3" /></label>
    <label>结果<textarea v-model="form.results" data-test="case-results" rows="2" /></label>
    <el-checkbox v-model="form.referenceable" data-test="case-referenceable">可在方案中对外引用（需客户同意）</el-checkbox>
    <div class="row">
      <el-button :disabled="saving" @click="showForm = false">取消</el-button>
      <el-button type="primary" :loading="saving" data-test="case-save" @click="save">保存</el-button>
    </div>
  </section>

  <section class="panel">
    <div class="row">
      <input v-model="filters.q" data-test="case-search" placeholder="标题 / 客户 / 痛点关键词" @keyup.enter="load" />
      <input v-model="filters.industry" data-test="case-filter-industry" placeholder="行业" @keyup.enter="load" />
      <select v-model="filters.size_band" data-test="case-filter-size">
        <option value="">全部规模</option>
        <option value="small">{{ label('small') }}</option>
        <option value="medium">{{ label('medium') }}</option>
        <option value="large">{{ label('large') }}</option>
      </select>
      <el-checkbox v-model="filters.referenceable" data-test="case-filter-referenceable">仅可引用</el-checkbox>
      <el-checkbox v-if="isAdmin" v-model="filters.include_inactive" data-test="case-filter-inactive">含已停用</el-checkbox>
      <el-button :loading="loading" data-test="case-apply" @click="page = 1; load()">查询</el-button>
      <el-button text data-test="case-reset" @click="reset">重置</el-button>
    </div>
    <p class="muted">共 {{ count }} 条</p>
    <p v-if="!loading && !rows.length" class="muted">还没有匹配的案例。</p>
    <ul v-else class="case-list">
      <li v-for="row in rows" :key="row.id" :data-test="`case-${row.id}`">
        <strong>{{ row.title }}</strong>
        <small>{{ row.industry }} · {{ label(row.size_band) }} · {{ row.customer_name || '匿名客户' }}</small>
        <el-tag v-if="row.referenceable" type="success" size="small" data-test="case-referenceable-tag">可引用</el-tag>
        <el-tag v-if="!row.is_active" type="info" size="small" data-test="case-inactive-tag">已停用</el-tag>
        <span v-if="row.results" class="case-result">{{ row.results }}</span>
        <span class="row">
          <el-button v-if="canWrite" text :data-test="`case-edit-${row.id}`" :disabled="!row.is_active" @click="openEdit(row)">编辑</el-button>
          <el-button
            v-if="canWrite"
            text
            :loading="busyId === row.id"
            :data-test="`case-toggle-${row.id}`"
            @click="toggle(row)"
          >{{ row.is_active ? '停用' : '恢复' }}</el-button>
        </span>
      </li>
    </ul>
    <el-pagination
      v-model:current-page="page"
      :page-size="20"
      :total="count"
      layout="prev, pager, next"
      @current-change="load"
    />
  </section>
</template>
