<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { matchCaseStudies } from '../api/case-studies'
import type { CaseStudy } from '../types/domain'
import { safeError } from '../utils/errors'
import { label } from '../utils/labels'

const props = defineProps<{ industry: string }>()
const rows = ref<CaseStudy[]>([])
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    // Ranked, not filtered: a near miss is still a starting point for the
    // presales writing the section.
    rows.value = await matchCaseStudies(props.industry, undefined, 5)
  } catch (e) {
    error.value = safeError(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
<template>
  <section class="panel" data-test="similar-cases">
    <h2>相似案例</h2>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="!loading && !rows.length" class="muted">
      案例库里还没有相近的案例——可以去
      <RouterLink to="/cases">案例库</RouterLink>补充一条。
    </p>
    <ul v-else class="case-list">
      <li v-for="row in rows" :key="row.id" :data-test="`similar-case-${row.id}`">
        <strong>{{ row.title }}</strong>
        <small>{{ row.industry }} · {{ label(row.size_band) }}</small>
        <el-tag v-if="row.referenceable" type="success" size="small">可引用</el-tag>
        <small>{{ row.referenceable ? row.customer_name : '匿名客户' }}</small>
      </li>
    </ul>
  </section>
</template>
