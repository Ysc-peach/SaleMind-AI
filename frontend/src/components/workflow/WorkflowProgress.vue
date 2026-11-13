<script setup lang="ts">
import type { SolutionWorkflow } from '../../types/workflow'

defineProps<{workflow:SolutionWorkflow}>()

const labels:Record<SolutionWorkflow['status'],string> = {
  QUEUED:'已排队，等待后台开始生成',
  RUNNING:'AI 方案正在后台生成',
  GENERATING:'AI 方案正在生成',
  WAITING_FOR_SALES_CONFIRMATION:'方案已生成，等待提交售前审核',
  WAITING_FOR_PRESALES_REVIEW:'等待售前审核',
  APPROVED:'技术审核已通过',
  CUSTOMER_INFO_REQUIRED:'需要补充客户信息',
  TECHNICAL_REVISION_REQUIRED:'需要修改技术方案',
  BLOCKED:'当前流程暂时无法继续',
  FAILED:'方案流程未能完成',
  CONFLICT:'流程状态已变化，请刷新',
}
</script>

<template>
  <section class="workflow-progress" data-test="workflow-progress" aria-live="polite">
    <strong>{{ labels[workflow.status] }}</strong>
  </section>
</template>
