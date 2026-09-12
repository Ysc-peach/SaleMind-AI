<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getReviewerInbox } from '../api/workspaces'
import Notice from '../components/Notice.vue'
import type { ReviewerInbox, ReviewInboxItem } from '../types/workspace'
import { dateTime } from '../utils/labels'
import { safeError } from '../utils/errors'

const data=ref<ReviewerInbox>(),loading=ref(false),error=ref('')
async function load(){loading.value=true;error.value='';try{data.value=await getReviewerInbox()}catch(e){error.value=safeError(e)}finally{loading.value=false}}
function when(item:ReviewInboxItem){return dateTime(item.decided_at||item.submitted_at)}
onMounted(load)
</script>
<template>
  <div class="page-heading"><div><p class="eyebrow">PRESALES WORKSPACE</p><h1>售前工作台</h1><p class="muted">优先处理分配给你的技术审核与方案修改。</p></div><el-button :loading="loading" @click="load">刷新</el-button></div>
  <Notice :error="error" :loading="loading" />
  <template v-if="data&&!loading">
    <section class="panel"><div class="section-heading"><h2>待审核方案 <span class="count">{{ data.pending_reviews.length }}</span></h2></div><div v-if="data.pending_reviews.length" class="review-list"><article v-for="item in data.pending_reviews" :key="item.review_id" class="review-card"><div><strong>{{ item.project_name }} · Solution V{{ item.solution_version }}</strong><p>{{ item.customer_name }} · Sales：{{ item.sales_owner_name }}</p><small>提交于 {{ when(item) }}</small></div><RouterLink :to="`/solutions/${item.solution_draft_id}`" class="action-link">开始审核</RouterLink></article></div><p v-else class="empty">当前没有待审核方案。</p></section>
    <section class="panel"><h2>需要技术修改 <span class="count">{{ data.technical_revisions.length }}</span></h2><div v-if="data.technical_revisions.length" class="review-list"><article v-for="item in data.technical_revisions" :key="item.review_id" class="review-card"><div><strong>{{ item.project_name }} · V{{ item.solution_version }}</strong><p>{{ item.customer_name }} · {{ item.comment }}</p></div><RouterLink :to="`/opportunities/${item.opportunity_id}?tab=solutions`" class="action-link">处理方案</RouterLink></article></div><p v-else class="empty">当前没有需要技术修改的方案。</p></section>
    <section class="panel"><h2>最近审核</h2><div v-if="data.recent_reviews.length" class="review-list"><article v-for="item in data.recent_reviews" :key="item.review_id" class="review-card"><div><strong>{{ item.project_name }} · V{{ item.solution_version }}</strong><small>{{ when(item) }}</small></div><RouterLink :to="`/solutions/${item.solution_draft_id}`">查看记录</RouterLink></article></div><p v-else class="empty">暂无近期审核记录。</p></section>
  </template>
</template>
