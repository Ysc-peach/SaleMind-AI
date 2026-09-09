<script setup lang="ts">
import Statements from '../Statements.vue'
import type { SolutionV1 } from '../../types/workflow'
defineProps<{solution:SolutionV1}>()
</script>

<template>
  <section class="panel"><h2>方案摘要</h2><Statements :items="solution.draft_payload.executive_summary" /></section>
  <section v-for="section in solution.draft_payload.solution_sections" :key="section.key" class="panel"><h2>{{section.title}}</h2><Statements :items="section.statements" /></section>
  <section v-if="solution.draft_payload.assumptions.length" class="panel"><h2>实施假设</h2><p v-for="(item,index) in solution.draft_payload.assumptions" :key="index" class="preserve">{{item.text}}</p></section>
  <section id="sources" class="panel"><h2>来源与证据</h2><p class="muted">以下为生成时保存的证据摘录，不代表来源永远有效。</p><p v-if="!solution.provenance.length">此版本没有企业文档引用。</p><details v-for="(source,index) in solution.provenance" :key="index"><summary>{{source.citation_label}} · 文档 #{{source.source_document_id}}</summary><blockquote class="preserve">{{source.source_excerpt}}</blockquote></details></section>
</template>
