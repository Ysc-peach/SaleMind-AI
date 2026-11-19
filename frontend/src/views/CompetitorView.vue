<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  createCompetitor,
  createStatement,
  decideStatement,
  listCompetitors,
  listStatements,
  setCompetitorActive,
} from '../api/competitors'
import type { Competitor, CompetitorStatement } from '../types/domain'
import { safeError } from '../utils/errors'
import Notice from '../components/Notice.vue'
import { useAuthStore } from '../stores/auth'

// Deliberately local maps: the global `label()` table already uses `approved`
// for the review decision, and a statement's approval is a different vocabulary.
const dimensionLabels: Record<string, string> = {
  deployment: '部署形态',
  data_residency: '数据驻留',
  identity_integration: '身份与集成',
  data_storage: '数据存储',
  document_processing: '文档处理',
  deliverables: '交付物',
  server_compatibility: '服务器兼容',
  knowledge_retrieval: '知识检索',
}
const statusLabels: Record<string, string> = {
  proposed: '待审批',
  approved: '已批准',
  rejected: '已拒绝',
}
const dimensions = Object.entries(dimensionLabels)

const auth = useAuthStore()
const canWrite = computed(
  () => auth.user?.role === 'presales' || auth.user?.role === 'admin',
)
const isAdmin = computed(() => auth.user?.role === 'admin')

const rows = ref<Competitor[]>([])
const loading = ref(false)
const error = ref('')
const feedback = ref('')
const busyId = ref<number | null>(null)
const search = ref('')
const includeInactive = ref(false)

const showCreate = ref(false)
const newName = ref('')
const newAliases = ref('')

const selected = ref<Competitor | null>(null)
const statements = ref<CompetitorStatement[]>([])
const statementCount = ref(0)
const statementLoading = ref(false)
const showStatementForm = ref(false)
const savingStatement = ref(false)
const statementForm = reactive({
  dimension: 'deployment',
  statement: '',
  source_url: '',
  published_on: new Date().toISOString().slice(0, 10),
})

async function loadCompetitors() {
  loading.value = true
  error.value = ''
  try {
    const data = await listCompetitors({
      q: search.value.trim(),
      include_inactive: isAdmin.value && includeInactive.value,
    })
    rows.value = data.results
  } catch (e) {
    error.value = safeError(e)
  } finally {
    loading.value = false
  }
}

async function loadStatements() {
  if (!selected.value) return
  statementLoading.value = true
  error.value = ''
  try {
    const data = await listStatements(selected.value.id)
    statements.value = data.results
    statementCount.value = data.count
  } catch (e) {
    error.value = safeError(e)
  } finally {
    statementLoading.value = false
  }
}

async function saveCompetitor() {
  if (!newName.value.trim()) {
    error.value = '请填写竞品名称。'
    return
  }
  loading.value = true
  error.value = ''
  try {
    await createCompetitor({
      name: newName.value.trim(),
      aliases: newAliases.value.trim(),
    })
    feedback.value = `已新增竞品：${newName.value.trim()}`
    newName.value = ''
    newAliases.value = ''
    showCreate.value = false
    await loadCompetitors()
  } catch (e) {
    error.value = safeError(e)
  } finally {
    loading.value = false
  }
}

async function toggleCompetitor(row: Competitor) {
  busyId.value = row.id
  error.value = ''
  try {
    await setCompetitorActive(row.id, !row.is_active)
    feedback.value = row.is_active
      ? `竞品已停用：${row.name}`
      : `竞品已恢复：${row.name}`
    await loadCompetitors()
  } catch (e) {
    error.value = safeError(e)
  } finally {
    busyId.value = null
  }
}

async function openStatements(row: Competitor) {
  selected.value = row
  showStatementForm.value = false
  await loadStatements()
}

async function saveStatement() {
  if (!selected.value) return
  if (!statementForm.statement.trim() || !statementForm.source_url.trim()) {
    error.value = '陈述与来源链接都必须填写。'
    return
  }
  savingStatement.value = true
  error.value = ''
  try {
    await createStatement(selected.value.id, {
      dimension: statementForm.dimension,
      statement: statementForm.statement.trim(),
      source_url: statementForm.source_url.trim(),
      published_on: statementForm.published_on || null,
    })
    feedback.value = '已登记陈述，等待管理员审批。'
    statementForm.statement = ''
    statementForm.source_url = ''
    showStatementForm.value = false
    await loadStatements()
  } catch (e) {
    // The server refuses negative claims with a specific code; safeError turns
    // that code into the instruction to quote the vendor instead.
    error.value = safeError(e)
  } finally {
    savingStatement.value = false
  }
}

async function decide(row: CompetitorStatement, approve: boolean) {
  busyId.value = row.id
  error.value = ''
  try {
    await decideStatement(row.id, approve)
    feedback.value = approve ? '陈述已批准。' : '陈述已拒绝。'
    await loadStatements()
  } catch (e) {
    error.value = safeError(e)
  } finally {
    busyId.value = null
  }
}

onMounted(loadCompetitors)
</script>
<template>
  <div class="page-heading">
    <div>
      <p class="eyebrow">COMPETITORS</p>
      <h1>竞品与公开陈述</h1>
      <p class="muted">只登记竞品自己公开宣称的内容并附来源；不做「不支持」这类否定判断。</p>
    </div>
    <el-button v-if="canWrite" type="primary" data-test="competitor-new" @click="showCreate = !showCreate">
      新建竞品
    </el-button>
  </div>
  <Notice :error="error" :loading="loading" />
  <p v-if="feedback" class="notice" role="status">{{ feedback }}</p>

  <section v-if="showCreate && canWrite" class="panel" data-test="competitor-form">
    <h2>新建竞品</h2>
    <div class="row">
      <input v-model="newName" data-test="competitor-name" placeholder="竞品名称（唯一）" />
      <input v-model="newAliases" data-test="competitor-aliases" placeholder="别名，逗号分隔（可留空）" />
      <el-button type="primary" :loading="loading" data-test="competitor-save" @click="saveCompetitor">保存</el-button>
    </div>
  </section>

  <section class="panel">
    <div class="row">
      <input v-model="search" data-test="competitor-search" placeholder="竞品名称" @keyup.enter="loadCompetitors" />
      <el-checkbox v-if="isAdmin" v-model="includeInactive" data-test="competitor-inactive" @change="loadCompetitors">含已停用</el-checkbox>
      <el-button :loading="loading" data-test="competitor-refresh" @click="loadCompetitors">刷新</el-button>
    </div>
    <p v-if="!loading && !rows.length" class="muted">还没有竞品记录。</p>
    <ul v-else class="case-list">
      <li v-for="row in rows" :key="row.id" :data-test="`competitor-${row.id}`">
        <strong>{{ row.name }}</strong>
        <small v-if="row.aliases">别名：{{ row.aliases }}</small>
        <el-tag v-if="!row.is_active" type="info" size="small" data-test="competitor-inactive-tag">已停用</el-tag>
        <span class="row">
          <el-button text :data-test="`competitor-open-${row.id}`" @click="openStatements(row)">查看陈述</el-button>
          <el-button
            v-if="canWrite"
            text
            :loading="busyId === row.id"
            :data-test="`competitor-toggle-${row.id}`"
            @click="toggleCompetitor(row)"
          >{{ row.is_active ? '停用' : '恢复' }}</el-button>
        </span>
      </li>
    </ul>
  </section>

  <section v-if="selected" class="panel" data-test="statement-panel">
    <h2>{{ selected.name }} · 公开陈述</h2>
    <p class="muted">共 {{ statementCount }} 条；只有「已批准」的陈述才会被比较表与方案引用。</p>
    <div class="row">
      <el-button v-if="canWrite" data-test="statement-new" @click="showStatementForm = !showStatementForm">登记陈述</el-button>
      <el-button :loading="statementLoading" data-test="statement-refresh" @click="loadStatements">刷新</el-button>
    </div>

    <div v-if="showStatementForm && canWrite" data-test="statement-form">
      <label>比较维度
        <select v-model="statementForm.dimension" data-test="statement-dimension">
          <option v-for="[value, name] in dimensions" :key="value" :value="value">{{ name }}</option>
        </select>
      </label>
      <label>公开陈述<textarea v-model="statementForm.statement" data-test="statement-text" rows="2" placeholder="引用对方原文，例如「支持容器化部署」" /></label>
      <label>来源链接<input v-model="statementForm.source_url" data-test="statement-url" placeholder="https://" /></label>
      <label>来源发布日期<input v-model="statementForm.published_on" data-test="statement-date" type="date" /></label>
      <el-button type="primary" :loading="savingStatement" data-test="statement-save" @click="saveStatement">提交审批</el-button>
    </div>

    <p v-if="!statementLoading && !statements.length" class="muted">暂无陈述。</p>
    <ul v-else class="case-list">
      <li v-for="row in statements" :key="row.id" :data-test="`statement-${row.id}`">
        <el-tag size="small">{{ dimensionLabels[row.dimension] || row.dimension }}</el-tag>
        <strong>{{ row.statement }}</strong>
        <small>{{ row.captured_on }} 采集<template v-if="row.published_on"> · 来源发布于 {{ row.published_on }}</template></small>
        <a :href="row.source_url" target="_blank" rel="noopener noreferrer">来源</a>
        <el-tag :type="row.status === 'approved' ? 'success' : row.status === 'rejected' ? 'info' : 'warning'" size="small" data-test="statement-status">
          {{ statusLabels[row.status] || row.status }}
        </el-tag>
        <span v-if="isAdmin" class="row">
          <el-button
            text
            :loading="busyId === row.id"
            :data-test="`statement-approve-${row.id}`"
            :disabled="row.status === 'approved'"
            @click="decide(row, true)"
          >批准</el-button>
          <el-button
            text
            :loading="busyId === row.id"
            :data-test="`statement-reject-${row.id}`"
            :disabled="row.status === 'rejected'"
            @click="decide(row, false)"
          >拒绝</el-button>
        </span>
      </li>
    </ul>
  </section>
</template>
