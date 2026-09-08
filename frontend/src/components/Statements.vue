<script setup lang="ts">
import type { Statement } from '../types/workflow'
import { label } from '../utils/labels'
defineProps<{items:Statement[]}>()
</script>
<template><article v-for="(item,index) in items" :key="index" class="statement"><span class="statement-type">{{label(item.type)}}</span><p class="preserve">{{item.text}}</p><a v-for="citation in item.citations" :key="citation" href="#sources" class="citation">[{{citation}}]</a></article></template>
