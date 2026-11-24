<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  createUser,
  listUsers,
  resetUserPassword,
  setUserActive,
  updateUser,
  type ManagedUser,
} from '../api/users'
import Notice from '../components/Notice.vue'
import { safeError } from '../utils/errors'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')

const roles = [
  { value: 'sales', label: '销售' },
  { value: 'presales', label: '售前' },
  { value: 'admin', label: '管理员' },
]

const rows = ref<ManagedUser[]>([])
const loading = ref(false)
const error = ref('')
const feedback = ref('')
const busyId = ref<number | null>(null)
const filters = reactive({ q: '', role: '', include_inactive: false })

const showCreate = ref(false)
const form = reactive({
  username: '',
  email: '',
  role: 'sales',
  password: '',
  first_name: '',
  last_name: '',
})
const saving = ref(false)

const resetTarget = ref<ManagedUser | null>(null)
const resetPassword = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    rows.value = (await listUsers({ ...filters })).results
  } catch (e) {
    error.value = safeError(e)
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!form.username.trim() || !form.email.trim() || !form.password) {
    error.value = '用户名、邮箱和初始密码都必须填写。'
    return
  }
  saving.value = true
  error.value = ''
  try {
    await createUser({
      username: form.username.trim(),
      email: form.email.trim(),
      role: form.role,
      password: form.password,
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
    })
    feedback.value = `已创建账号：${form.username.trim()}`
    form.username = ''
    form.email = ''
    form.password = ''
    form.first_name = ''
    form.last_name = ''
    showCreate.value = false
    await load()
  } catch (e) {
    error.value = safeError(e)
  } finally {
    saving.value = false
  }
}

async function changeRole(user: ManagedUser, role: string) {
  busyId.value = user.id
  error.value = ''
  try {
    await updateUser(user.id, { role })
    feedback.value = `已调整 ${user.username} 的角色，该用户的现有会话已失效。`
    await load()
  } catch (e) {
    // A refused demotion must leave the select showing the server's truth, and
    // the reason must survive that reload: load() clears the error slot first.
    const reason = safeError(e)
    await load()
    error.value = reason
  } finally {
    busyId.value = null
  }
}

async function toggleActive(user: ManagedUser) {
  busyId.value = user.id
  error.value = ''
  try {
    await setUserActive(user.id, !user.is_active)
    feedback.value = user.is_active
      ? `已停用 ${user.username}，其会话已失效`
      : `已恢复 ${user.username}`
    await load()
  } catch (e) {
    error.value = safeError(e)
  } finally {
    busyId.value = null
  }
}

function openReset(user: ManagedUser) {
  resetTarget.value = user
  resetPassword.value = ''
  error.value = ''
}

async function submitReset() {
  if (!resetTarget.value) return
  if (!resetPassword.value) {
    error.value = '请填写新密码。'
    return
  }
  busyId.value = resetTarget.value.id
  error.value = ''
  try {
    await resetUserPassword(resetTarget.value.id, resetPassword.value)
    feedback.value = `已重置 ${resetTarget.value.username} 的密码，其会话已失效`
    resetTarget.value = null
    resetPassword.value = ''
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
      <p class="eyebrow">TEAM</p>
      <h1>团队账号</h1>
      <p class="muted">
        建号、调整角色、停用与重置密码。改角色与停用会让该用户所有会话立即失效。
      </p>
    </div>
    <el-button v-if="isAdmin" type="primary" data-test="team-new" @click="showCreate = !showCreate">
      新建账号
    </el-button>
  </div>
  <Notice :error="error" :loading="loading" />
  <p v-if="feedback" class="notice" role="status">{{ feedback }}</p>

  <section v-if="showCreate && isAdmin" class="panel" data-test="team-form">
    <h2>新建账号</h2>
    <div class="row">
      <input v-model="form.username" data-test="team-username" placeholder="用户名" />
      <input v-model="form.email" data-test="team-email" placeholder="邮箱" />
      <select v-model="form.role" data-test="team-role">
        <option v-for="item in roles" :key="item.value" :value="item.value">{{ item.label }}</option>
      </select>
      <input v-model="form.password" data-test="team-password" type="password" placeholder="初始密码" />
    </div>
    <div class="row">
      <input v-model="form.first_name" data-test="team-first" placeholder="名" />
      <input v-model="form.last_name" data-test="team-last" placeholder="姓" />
      <el-button type="primary" :loading="saving" data-test="team-save" @click="save">创建</el-button>
    </div>
  </section>

  <section class="panel">
    <div class="row">
      <input v-model="filters.q" data-test="team-search" placeholder="用户名 / 姓名 / 邮箱" @keyup.enter="load" />
      <select v-model="filters.role" data-test="team-filter-role" @change="load">
        <option value="">全部角色</option>
        <option v-for="item in roles" :key="item.value" :value="item.value">{{ item.label }}</option>
      </select>
      <el-checkbox v-if="isAdmin" v-model="filters.include_inactive" data-test="team-inactive" @change="load">
        含已停用
      </el-checkbox>
      <el-button :loading="loading" data-test="team-refresh" @click="load">刷新</el-button>
    </div>
    <p v-if="!loading && !rows.length" class="muted">没有符合条件的账号。</p>
    <table v-else class="team-table">
      <thead>
        <tr><th>账号</th><th>姓名</th><th>邮箱</th><th>角色</th><th>状态</th><th v-if="isAdmin">操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="user in rows" :key="user.id" :data-test="`team-row-${user.id}`">
          <td>{{ user.username }}</td>
          <td>{{ [user.first_name, user.last_name].filter(Boolean).join(' ') || '—' }}</td>
          <td>{{ user.email }}</td>
          <td>
            <select
              v-if="isAdmin"
              :value="user.role"
              :data-test="`team-role-${user.id}`"
              :disabled="busyId === user.id"
              @change="changeRole(user, ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="item in roles" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
            <span v-else>{{ user.role_label }}</span>
          </td>
          <td>
            <el-tag v-if="!user.is_active" type="info" data-test="team-inactive-tag">已停用</el-tag>
            <span v-else>在用</span>
          </td>
          <td v-if="isAdmin">
            <el-button
              text
              :loading="busyId === user.id"
              :data-test="`team-toggle-${user.id}`"
              @click="toggleActive(user)"
            >{{ user.is_active ? '停用' : '恢复' }}</el-button>
            <el-button text :data-test="`team-reset-${user.id}`" @click="openReset(user)">重置密码</el-button>
          </td>
        </tr>
      </tbody>
    </table>
  </section>

  <section v-if="resetTarget" class="panel" data-test="team-reset-form">
    <h2>重置密码 · {{ resetTarget.username }}</h2>
    <p class="muted">重置后该用户所有会话立即失效，需要用新密码重新登录。</p>
    <div class="row">
      <input v-model="resetPassword" data-test="team-new-password" type="password" placeholder="新密码" />
      <el-button type="primary" :loading="busyId === resetTarget.id" data-test="team-reset-save" @click="submitReset">
        确认重置
      </el-button>
      <el-button text @click="resetTarget = null">取消</el-button>
    </div>
  </section>
</template>
<style scoped>
.team-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.team-table th, .team-table td { padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: left; }
.team-table th { color: #64748b; font-weight: 600; }
.team-table select { padding: 4px 6px; border: 1px solid #cbd5e1; border-radius: 6px; }
</style>
