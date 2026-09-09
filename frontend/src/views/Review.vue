<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { decideProposal, getProposalItems, listProposals } from '../api/client'
import type { KnowledgeItem } from '../types'

const queue = ref<KnowledgeItem[]>([])
const index = ref(0)
const items = ref<KnowledgeItem[]>([])
const note = ref('')
const loading = ref(true)
const busy = ref('')
const error = ref('')
const done = ref(0)

const current = computed<KnowledgeItem | null>(() => queue.value[index.value] ?? null)

// The proposal's own text carries the model's reasoning under a 【共同逻辑】
// heading; the item list above it is a truncated snapshot we deliberately
// ignore in favour of the live items fetched below.
const sharedLogic = computed(() => {
  const body = current.value?.content ?? ''
  const match = body.match(/【共同逻辑】\s*\n([\s\S]*?)(?=\n\s*(?:建议|【)|$)/)
  return match ? match[1].trim() : body
})

async function loadItems() {
  items.value = []
  if (!current.value) return
  try {
    items.value = await getProposalItems(current.value.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    queue.value = await listProposals(100)
    index.value = 0
    await loadItems()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function decide(verdict: 'approve' | 'dismiss') {
  const proposal = current.value
  if (!proposal || busy.value) return
  busy.value = verdict
  try {
    await decideProposal(proposal.id, verdict, note.value.trim())
    // Drop it from the local queue rather than refetching: the next item
    // should appear instantly, and a decided proposal is gone from the
    // server's queue anyway.
    queue.value.splice(index.value, 1)
    if (index.value >= queue.value.length) index.value = Math.max(0, queue.value.length - 1)
    note.value = ''
    done.value += 1
    await loadItems()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = ''
  }
}

async function skip(step: number) {
  if (!queue.value.length) return
  index.value = (index.value + step + queue.value.length) % queue.value.length
  note.value = ''
  await loadItems()
}

onMounted(load)
</script>

<template>
  <div class="review-head">
    <h1>待审</h1>
    <span v-if="queue.length" class="count">
      剩 {{ queue.length }} 条<template v-if="done"> · 本次已处理 {{ done }}</template>
    </span>
  </div>

  <div v-if="error" class="error-bar">{{ error }}</div>
  <p v-if="loading" class="empty">加载中…</p>

  <p v-else-if="!current" class="empty">
    没有待审的提议了{{ done ? '，本次处理了 ' + done + ' 条' : '' }}。
  </p>

  <template v-else>
    <div class="card">
      <h2>
        {{ current.title.replace('待审 · ', '') }}
        <span class="count">{{ index + 1 }} / {{ queue.length }}</span>
      </h2>

      <p class="logic">{{ sharedLogic }}</p>

      <div class="refs">
        <p v-if="!items.length" class="empty">正在读取被引用的条目…</p>
        <article v-for="it in items" :key="it.id" class="ref">
          <h3>
            <RouterLink :to="`/knowledge/${it.id}`">#{{ it.id }} {{ it.title }}</RouterLink>
          </h3>
          <pre>{{ it.content }}</pre>
        </article>
      </div>

      <input v-model="note" class="note"
             placeholder="可选：说一句你为什么这么判断（会写进判断标准的依据里）" />

      <div class="actions">
        <button class="btn primary" :disabled="!!busy" @click="decide('approve')">
          {{ busy === 'approve' ? '处理中…' : '同意' }}
        </button>
        <button class="btn" :disabled="!!busy" @click="decide('dismiss')">
          {{ busy === 'dismiss' ? '处理中…' : '忽略' }}
        </button>
        <span class="spacer" />
        <button class="btn small" :disabled="queue.length < 2" @click="skip(-1)">上一条</button>
        <button class="btn small" :disabled="queue.length < 2" @click="skip(1)">下一条</button>
      </div>
      <p class="hint">
        同意 = 给这几条互相打上关联标签，之后能一起查到；忽略 = 不动任何知识，只把这条提议归档。
        两种选择都会被记进判断标准的依据，用来学你的判断口味。
      </p>
    </div>
  </template>
</template>

<style scoped>
.review-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 12px; }
.review-head h1 { margin: 0; font-size: 1.3rem; }
.count { color: var(--text-dim); font-size: 0.85rem; font-weight: normal; }
.logic {
  margin: 0 0 14px; padding: 12px 14px; line-height: 1.7;
  background: var(--bg-hover); border-radius: 8px;
  border-left: 3px solid var(--accent-2);
}
.refs { display: grid; gap: 10px; }
.ref { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.ref h3 { margin: 0 0 6px; font-size: 0.92rem; font-weight: 600; }
.ref pre {
  margin: 0; white-space: pre-wrap; word-break: break-word;
  font-family: inherit; font-size: 0.88rem; line-height: 1.65; color: var(--text-dim);
}
.note { width: 100%; margin: 14px 0 10px; }
.actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.spacer { flex: 1; }
.hint { margin: 10px 0 0; font-size: 0.8rem; color: var(--text-dim); line-height: 1.6; }
</style>
