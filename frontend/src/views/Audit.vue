<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { getAudit, type AuditEntry } from '../api/client'
import { fmtTime } from '../types'

const entries = ref<AuditEntry[]>([])
const note = ref('')
const loading = ref(true)
const error = ref('')
const writesOnly = ref(true)
const agent = ref('')

const WRITE = /^(POST|PATCH|PUT|DELETE)$/

async function load() {
  loading.value = true
  error.value = ''
  try {
    const body = await getAudit({ limit: 300, writesOnly: writesOnly.value, agent: agent.value })
    entries.value = body.entries
    note.value = body.note
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

const agents = computed(() => {
  const seen = new Map<string, number>()
  for (const e of entries.value) seen.set(e.agent, (seen.get(e.agent) ?? 0) + 1)
  return Array.from(seen.entries()).sort((a, b) => b[1] - a[1])
})

watch([writesOnly, agent], load)
onMounted(load)
</script>

<template>
  <div class="audit-head">
    <h1>访问日志</h1>
    <span class="count">{{ entries.length }} 条</span>
  </div>

  <p class="warn">{{ note || '调用方身份由其自行声明，未经验证。' }}</p>

  <div class="controls">
    <label><input v-model="writesOnly" type="checkbox" /> 只看写入操作</label>
    <label>
      调用方
      <select v-model="agent">
        <option value="">全部</option>
        <option v-for="[name, n] in agents" :key="name" :value="name">{{ name }}（{{ n }}）</option>
      </select>
    </label>
    <button class="btn small" @click="load">刷新</button>
  </div>

  <div v-if="error" class="error-bar">{{ error }}</div>
  <p v-if="loading" class="empty">加载中…</p>
  <p v-else-if="!entries.length" class="empty">还没有记录。</p>

  <table v-else class="log">
    <thead>
      <tr><th>时间</th><th>调用方</th><th>操作</th><th>对象</th><th>结果</th></tr>
    </thead>
    <tbody>
      <tr v-for="(e, i) in entries" :key="i" :class="{ write: WRITE.test(e.method) }">
        <td class="dim">{{ fmtTime(e.at) }}</td>
        <td>
          {{ e.agent }}
          <div v-if="e.machine" class="dim">{{ e.machine }}</div>
        </td>
        <td><span class="method" :class="e.method.toLowerCase()">{{ e.method }}</span></td>
        <td class="path">{{ e.path }}<span v-if="e.query" class="dim">?{{ e.query }}</span></td>
        <td :class="{ bad: e.status >= 400 }">{{ e.status }}<span class="dim"> · {{ e.ms }}ms</span></td>
      </tr>
    </tbody>
  </table>
</template>

<style scoped>
.audit-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 6px; }
.audit-head h1 { margin: 0; font-size: 1.3rem; }
.count, .dim { color: var(--text-dim); font-size: 0.82rem; }
.warn {
  margin: 0 0 10px; padding: 8px 12px; font-size: 0.82rem; line-height: 1.6;
  border-left: 3px solid var(--accent-2); background: var(--bg-hover); border-radius: 6px;
}
.controls { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; font-size: 13px; }
.controls label { display: inline-flex; align-items: center; gap: 6px; }
.log { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.log th {
  text-align: left; padding: 6px 8px; color: var(--text-dim);
  border-bottom: 1px solid var(--border); font-weight: 500;
}
.log td { padding: 6px 8px; border-bottom: 1px solid rgba(148, 163, 184, 0.12); vertical-align: top; }
.log tr.write { background: rgba(144, 190, 109, 0.06); }
.method {
  display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 0.75rem;
  background: rgba(148, 163, 184, 0.18);
}
.method.post, .method.patch, .method.put { background: rgba(144, 190, 109, 0.25); }
.method.delete { background: rgba(230, 90, 80, 0.25); }
.path { font-family: ui-monospace, monospace; word-break: break-all; }
.bad { color: var(--danger); }
</style>
