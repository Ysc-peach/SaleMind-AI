<script setup lang="ts">
import { ref, watch } from 'vue'
import { listSolutions } from '../api/solutions'
import type { SolutionSummary } from '../types/workflow'
import { safeError } from '../utils/errors'
import { label, dateTime } from '../utils/labels'
import Notice from './Notice.vue'
const props=defineProps<{opportunityId:number;reviewMode?:boolean}>()
const rows=ref<SolutionSummary[]>([]),page=ref(1),total=ref(0),loading=ref(false),error=ref('')
async function load(){loading.value=true;error.value='';rows.value=[];try{const data=await listSolutions(props.opportunityId,page.value);rows.value=data.results;total.value=data.count}catch(e){error.value=safeError(e)}finally{loading.value=false}}
watch(()=>props.opportunityId,()=>{page.value=1;load()},{immediate:true})
</script>
<template><section class="panel"><div class="page-heading"><div><h2>{{reviewMode?'方案审核':'技术方案版本'}}</h2><p class="muted">{{reviewMode?'打开具体版本查看审核历史与可执行动作。审核由服务端校验权限。':'每次生成创建独立版本，历史正文不可原地修改。'}}</p></div><el-button :disabled="loading" @click="load">刷新</el-button></div><Notice :error="error" :loading="loading" /><p v-if="!loading&&!error&&!rows.length">暂无技术方案。请前往 AI需求分析，选择快照并生成。</p><el-table v-if="rows.length" :data="rows"><el-table-column label="方案 / 版本" min-width="210"><template #default="{row}"><RouterLink :to="`/solutions/${row.id}${reviewMode?'#review':''}`">V{{row.version}} · {{row.title}}</RouterLink></template></el-table-column><el-table-column label="状态" min-width="160"><template #default="{row}">{{label(row.review_status)}}<span v-if="row.is_stale" class="stale-badge">已过期</span></template></el-table-column><el-table-column label="分析快照" width="110"><template #default="{row}">#{{row.analysis_id}}</template></el-table-column><el-table-column label="生成时间" min-width="170"><template #default="{row}">{{dateTime(row.created_at)}}</template></el-table-column></el-table><el-pagination v-if="total>20" v-model:current-page="page" :total="total" :page-size="20" layout="prev, pager, next" @current-change="load" /></section></template>
