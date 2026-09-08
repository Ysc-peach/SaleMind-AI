<script setup lang="ts">defineProps<{ error?: string; loading?: boolean }>()</script>
<template><div v-if="error" class="notice error" role="alert">{{ error }}</div><div v-else-if="loading" class="notice" role="status">正在加载，请稍候…</div></template>
