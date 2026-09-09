<script setup lang="ts">
import type { SafeSolutionSource } from '../../types/workflow'
defineProps<{open:boolean;sources:SafeSolutionSource[]}>()
const emit=defineEmits<{close:[]}>()
</script>

<template>
  <aside v-if="open" class="source-drawer" aria-label="声明来源">
    <div class="page-heading"><h3>来源依据</h3><el-button @click="emit('close')">关闭</el-button></div>
    <p v-if="!sources.length" class="muted">该声明没有企业文档来源。</p>
    <article v-for="source in sources" :key="source.source_id" class="source-card"><strong>{{source.source_id}} · {{source.document_title}}</strong><blockquote class="preserve">{{source.source_excerpt}}</blockquote></article>
  </aside>
</template>

<style scoped>
.source-drawer{position:fixed;inset:0 0 0 auto;z-index:20;width:min(440px,92vw);overflow:auto;background:#fff;border-left:1px solid #dfe5ee;box-shadow:-12px 0 32px rgba(31,45,71,.14);padding:24px}.source-card{margin-top:16px;padding-top:16px;border-top:1px solid #e8ecf2}.source-card blockquote{margin:10px 0 0}
</style>
