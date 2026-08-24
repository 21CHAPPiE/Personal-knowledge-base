<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { appendProjectContext, getProjectContext } from '../api/client'
import type { ProjectContext } from '../types'
import { fmtTime, STATUS_LABELS, TYPE_LABELS } from '../types'

const props = defineProps<{ id: number | string }>()
const ctx = ref<ProjectContext | null>(null)
const error = ref('')
const appendText = ref('')
const busy = ref(false)
const tab = ref<'knowledge' | 'context'>('knowledge')

async function load() {
  try {
    ctx.value = await getProjectContext(Number(props.id))
    error.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(load)
watch(() => props.id, load)

async function append() {
  if (busy.value || !appendText.value.trim() || !ctx.value) return
  busy.value = true
  try {
    await appendProjectContext(ctx.value.project.id, appendText.value.trim())
    appendText.value = ''
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

function contextText(c: ProjectContext): string {
  const p = c.project
  const lines: string[] = []
  lines.push(`# ${p.name}`)
  lines.push(`状态: ${STATUS_LABELS[p.status] || p.status}`)
  if (p.description) lines.push(`简介: ${p.description}`)
  const s = c.statistics
  lines.push('')
  lines.push(`知识条目总数: ${s.total_items}`)
  if (s.by_type && Object.keys(s.by_type).length) {
    lines.push('类型分布: ' + Object.entries(s.by_type).map(([k, v]) => `${TYPE_LABELS[k] || k} ${v}`).join('，'))
  }
  if (s.first_activity) lines.push(`首次活动: ${fmtTime(s.first_activity)}`)
  if (s.last_activity) lines.push(`最近活动: ${fmtTime(s.last_activity)}`)
  lines.push('')
  lines.push('## 最近知识（按更新时间）')
  if (!c.recent_items.length) lines.push('（暂无）')
  for (const k of c.recent_items) {
    lines.push(`- [${fmtTime(k.updated_at)}] ${k.title}（${TYPE_LABELS[k.type] || k.type}）`)
    if (k.content_preview) lines.push(`  ${k.content_preview.slice(0, 120)}`)
  }
  return lines.join('\n')
}
</script>

<template>
  <div v-if="error && !ctx" class="error-bar">{{ error }}</div>
  <div v-if="ctx">
    <h1 style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
      {{ ctx.project.name }}
      <span class="badge">{{ STATUS_LABELS[ctx.project.status] || ctx.project.status }}</span>
    </h1>
    <div class="card" v-if="ctx.project.description">
      <div class="detail-content" style="color:var(--text-dim);font-size:0.9rem;">{{ ctx.project.description }}</div>
    </div>

    <div class="stat-grid" style="grid-template-columns:repeat(4,1fr);">
      <div class="stat"><div class="num" style="font-size:1.1rem;">{{ ctx.statistics.total_items }}</div><div class="label">知识条目</div></div>
      <div class="stat"><div class="num" style="font-size:1.1rem;">{{ ctx.timeline.reduce((a, b) => a + b.count, 0) }}</div><div class="label">近30天新增</div></div>
      <div class="stat"><div class="num" style="font-size:0.85rem;line-height:2.2rem;">{{ ctx.statistics.last_activity ? fmtTime(ctx.statistics.last_activity).slice(5) : '-' }}</div><div class="label">最近活动</div></div>
      <div class="stat"><div class="num" style="font-size:0.85rem;line-height:2.2rem;">{{ ctx.statistics.first_activity ? fmtTime(ctx.statistics.first_activity).slice(0, 10) : '-' }}</div><div class="label">首次活动</div></div>
    </div>

    <div class="card">
      <h2>追加项目进展</h2>
      <div class="field">
        <textarea v-model="appendText" rows="3" placeholder="记录一条进展，例如：完成数据库设计，明天开始写 API"></textarea>
      </div>
      <button class="btn primary" :disabled="busy || !appendText.trim()" @click="append">
        {{ busy ? '追加中…' : '追加进展' }}
      </button>
      <div style="font-size:0.75rem;color:var(--text-faint);margin-top:6px;">
        进展以「项目进展」类型知识保存，Coding Agent 通过 MCP 也能追加。
      </div>
    </div>

    <div class="section-title" style="margin-top:18px;">
      项目知识
      <div style="display:flex;gap:4px;">
        <button class="btn small" :class="{ primary: tab === 'knowledge' }" @click="tab = 'knowledge'">列表</button>
        <button class="btn small" :class="{ primary: tab === 'context' }" @click="tab = 'context'">上下文</button>
      </div>
    </div>

    <div v-if="tab === 'knowledge'">
      <div v-if="!ctx.recent_items.length" class="empty">项目下还没有知识</div>
      <RouterLink v-for="k in ctx.recent_items" :key="k.id" :to="`/knowledge/${k.id}`" class="item">
        <div class="title-row">
          <span class="badge" :class="`type-${k.type}`">{{ TYPE_LABELS[k.type] || k.type }}</span>
          <span class="title">{{ k.title }}</span>
        </div>
        <div v-if="k.content_preview" class="preview">{{ k.content_preview }}</div>
        <div class="meta">{{ fmtTime(k.updated_at) }}</div>
      </RouterLink>
    </div>

    <div v-else>
      <pre class="context-block">{{ contextText(ctx) }}</pre>
      <div style="font-size:0.75rem;color:var(--text-faint);margin-top:6px;">
        这段文本即 MCP 工具 project_get_context 返回的内容形态，可直接复制给 Coding Agent。
      </div>
    </div>

    <div class="section-title" style="margin-top:18px;">近 30 天时间线</div>
    <div class="card">
      <div v-if="!ctx.timeline.length" class="empty">近 30 天没有新增</div>
      <ul v-else class="timeline">
        <li v-for="t in [...ctx.timeline].reverse()" :key="t.date">
          <div class="day">{{ t.date }}</div>
          <div class="entry">新增 {{ t.count }} 条知识</div>
        </li>
      </ul>
    </div>
  </div>
</template>
