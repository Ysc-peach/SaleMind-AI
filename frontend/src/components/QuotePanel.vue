<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  addQuoteLine,
  decideDiscount,
  getQuote,
  listPriceBook,
  rebindQuote,
  removeQuoteLine,
  saveQuote,
  setLineQuantity,
} from '../api/quotes'
import type { PriceBookEntry, Quote } from '../types/domain'
import { safeError } from '../utils/errors'
import { useAuthStore } from '../stores/auth'

const props = defineProps<{ opportunityId: number; canWrite: boolean }>()
const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')

const quote = ref<Quote | null>(null)
const entries = ref<PriceBookEntry[]>([])
const loading = ref(false)
const error = ref('')
const feedback = ref('')
const busy = ref(false)
const outdated = ref(false)

const entryId = ref<number | null>(null)
const quantity = ref('1')
const discount = ref('0')
const comment = ref('')

const write = computed(() => props.canWrite)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [current, book] = await Promise.all([
      getQuote(props.opportunityId),
      listPriceBook(),
    ])
    quote.value = current
    entries.value = book.results.filter(item => item.is_active)
    discount.value = current ? current.discount_percent : '0'
    if (!entryId.value && entries.value.length) {
      entryId.value = entries.value[0].id
    }
  } catch (e) {
    error.value = safeError(e)
  } finally {
    loading.value = false
  }
}

function noteOutdated(e: unknown) {
  const code = (e as { response?: { data?: { code?: string } } })?.response?.data
    ?.code
  outdated.value = code === 'quote_outdated'
}

async function addLine() {
  if (!entryId.value) return
  busy.value = true
  error.value = ''
  try {
    quote.value = await addQuoteLine(props.opportunityId, {
      price_book_entry: entryId.value,
      quantity: quantity.value || '1',
    })
    outdated.value = false
    quantity.value = '1'
    feedback.value = '已加入报价'
  } catch (e) {
    noteOutdated(e)
    error.value = safeError(e)
  } finally {
    busy.value = false
  }
}

async function changeQuantity(lineId: number, value: string) {
  busy.value = true
  error.value = ''
  try {
    await setLineQuantity(lineId, value)
    await load()
  } catch (e) {
    noteOutdated(e)
    error.value = safeError(e)
  } finally {
    busy.value = false
  }
}

async function removeLine(lineId: number) {
  busy.value = true
  error.value = ''
  try {
    await removeQuoteLine(lineId)
    await load()
    feedback.value = '已撤下该行（保留记录，不计入合计）'
  } catch (e) {
    noteOutdated(e)
    error.value = safeError(e)
  } finally {
    busy.value = false
  }
}

async function saveDiscount() {
  busy.value = true
  error.value = ''
  try {
    quote.value = await saveQuote(props.opportunityId, {
      discount_percent: discount.value,
    })
    feedback.value = '折扣已保存'
  } catch (e) {
    noteOutdated(e)
    error.value = safeError(e)
  } finally {
    busy.value = false
  }
}

async function rebind() {
  busy.value = true
  error.value = ''
  try {
    quote.value = await rebindQuote(props.opportunityId)
    outdated.value = false
    feedback.value = '已改绑到最新方案版本'
  } catch (e) {
    error.value = safeError(e)
  } finally {
    busy.value = false
  }
}

async function decide(approve: boolean) {
  busy.value = true
  error.value = ''
  try {
    quote.value = await decideDiscount(props.opportunityId, approve, comment.value)
    comment.value = ''
    feedback.value = approve ? '折扣已批准' : '折扣已拒绝'
  } catch (e) {
    error.value = safeError(e)
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>
<template>
  <section class="panel" data-test="quote-panel">
    <h2>报价（未含税）</h2>
    <p class="muted">
      单价在加入时冻结；方案重新生成后需改绑到最新版本才能继续编辑或导出。
    </p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="feedback" role="status">{{ feedback }}</p>
    <div v-if="outdated" role="alert" data-test="quote-outdated">
      报价对应的是旧方案版本。
      <el-button v-if="write" text data-test="quote-rebind" :loading="busy" @click="rebind">
        改绑到最新版本
      </el-button>
    </div>

    <div v-if="write" class="row">
      <select v-model="entryId" data-test="quote-entry">
        <option v-for="item in entries" :key="item.id" :value="item.id">
          {{ item.sku }} · {{ item.name }} · {{ item.unit_price }} {{ item.currency }}
        </option>
      </select>
      <input v-model="quantity" data-test="quote-quantity" placeholder="数量" />
      <el-button type="primary" :loading="busy" data-test="quote-add" @click="addLine">
        加入报价
      </el-button>
    </div>

    <p v-if="!quote || !quote.lines.length" class="muted">尚无报价行。</p>
    <table v-else class="quote-table">
      <thead>
        <tr><th>物料</th><th>数量</th><th>单价</th><th>小计</th><th v-if="write">操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="line in quote.lines" :key="line.id" :data-test="`quote-line-${line.id}`">
          <td>{{ line.sku }} · {{ line.name }}</td>
          <td>
            <input
              v-if="write"
              :value="line.quantity"
              :data-test="`quote-qty-${line.id}`"
              @change="changeQuantity(line.id, ($event.target as HTMLInputElement).value)"
            />
            <span v-else>{{ line.quantity }}</span>
          </td>
          <td>{{ line.unit_price }}</td>
          <td>{{ line.subtotal }}</td>
          <td v-if="write">
            <el-button text :data-test="`quote-remove-${line.id}`" @click="removeLine(line.id)">
              撤下
            </el-button>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="quote" class="row" data-test="quote-totals">
      <label>整体折扣（%）
        <input v-model="discount" data-test="quote-discount" :disabled="!write" />
      </label>
      <el-button v-if="write" :loading="busy" data-test="quote-save-discount" @click="saveDiscount">
        保存折扣
      </el-button>
      <span>小计 {{ quote.subtotal }} · 折让 {{ quote.discount_amount }} · 合计 {{ quote.total }} {{ quote.currency }}</span>
    </div>

    <div v-if="quote" class="row" data-test="quote-approval">
      <template v-if="!quote.discount_approval.required">
        <el-tag type="success" size="small">折扣未超阈值（{{ quote.discount_approval.threshold_percent }}%）</el-tag>
      </template>
      <template v-else-if="quote.discount_approval.approved">
        <el-tag type="success" size="small" data-test="quote-approved">
          已批准 {{ quote.discount_approval.approved_percent }}%（{{ quote.discount_approval.approved_by_name }}）
        </el-tag>
      </template>
      <template v-else>
        <el-tag type="warning" size="small" data-test="quote-pending">折扣待管理员批准</el-tag>
        <template v-if="isAdmin">
          <input v-model="comment" data-test="quote-comment" placeholder="说明（可选）" />
          <el-button type="primary" :loading="busy" data-test="quote-approve" @click="decide(true)">批准</el-button>
          <el-button :loading="busy" data-test="quote-reject" @click="decide(false)">拒绝</el-button>
        </template>
      </template>
    </div>
  </section>
</template>
