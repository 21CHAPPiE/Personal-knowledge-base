<script setup lang="ts">
import { recordVisit } from '../recentlyViewed'
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  deleteKnowledge, getKnowledge, getLLMStatus, listProjects,
  suggestTags, summarizeKnowledge, updateKnowledge, uploadAttachment,
} from '../api/client'
import type { KnowledgeItem, Project } from '../types'
import { fmtSize, fmtTime, TYPE_LABELS } from '../types'

const props = defineProps<{ id: number | string }>()
const router = useRouter()

const item = ref<KnowledgeItem | null>(null)
const projects = ref<Project[]>([])
const llm = ref<{ configured: boolean; provider: string } | null>(null)
const error = ref('')
const notice = ref('')
const editing = ref(false)
const draft = ref({ title: '', content: '', project_id: '' as number | '', tags: '' })
const busy = ref('')

async function load() {
  try {
    item.value = await getKnowledge(Number(props.id))
    recordVisit(item.value.id, item.value.title)
    projects.value = await listProjects()
    const s = await getLLMStatus()
    llm.value = { configured: s.llm.configured, provider: s.llm.provider }
    error.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(load)
watch(() => props.id, load)

function startEdit() {
  if (!item.value) return
  draft.value = {
    title: item.value.title,
    content: item.value.content,
    project_id: item.value.project_id ?? '',
    tags: item.value.tags.join(', '),
  }
  editing.value = true
  notice.value = ''
}

async function save() {
  if (!item.value) return
  busy.value = 'save'
  try {
    const patch: Parameters<typeof updateKnowledge>[1] = {
      title: draft.value.title,
      content: draft.value.content,
      project_id: draft.value.project_id === '' ? null : Number(draft.value.project_id),
      tags: draft.value.tags.split(',').map((t) => t.trim()).filter(Boolean),
    }
    item.value = await updateKnowledge(item.value.id, patch)
    editing.value = false
    notice.value = '已保存'
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = ''
  }
}

async function runSummary() {
  if (!item.value) return
  busy.value = 'sum'
  try {
    const r = await summarizeKnowledge(item.value.id)
    await load()
    notice.value = r.fallback
      ? `摘要已生成（本地回退：${r.provider}）`
      : `摘要已生成（${r.provider}）`
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = ''
  }
}

async function runTags() {
  if (!item.value) return
  busy.value = 'tags'
  try {
    const r = await suggestTags(item.value.id, true)
    await load()
    notice.value = r.fallback
      ? `标签推荐完成（${r.provider} 未配置，结果可能为空）`
      : `已应用推荐标签（${r.provider}）`
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = ''
  }
}

async function addFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !item.value) return
  busy.value = 'file'
  try {
    await uploadAttachment(item.value.id, file)
    await load()
    notice.value = `附件 ${file.name} 已上传`
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    busy.value = ''
    input.value = ''
  }
}

async function remove() {
  if (!item.value) return
  if (!confirm(`删除「${item.value.title}」？附件也会删除。`)) return
  busy.value = 'del'
  try {
    await deleteKnowledge(item.value.id)
    router.push('/knowledge')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div v-if="error && !item" class="error-bar">{{ error }}</div>
  <div v-if="item">
    <div class="card">
      <template v-if="!editing">
        <h1 style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          <span class="badge" :class="`type-${item.type}`">{{ TYPE_LABELS[item.type] || item.type }}</span>
          {{ item.title }}
        </h1>
        <div class="meta" style="color:var(--text-faint);font-size:0.78rem;margin-bottom:8px;">
          创建 {{ fmtTime(item.created_at) }} · 更新 {{ fmtTime(item.updated_at) }}
          <template v-if="item.project_name"> · <RouterLink :to="`/projects/${item.project_id}`">{{ item.project_name }}</RouterLink></template>
          <template v-if="item.tags.length"> · <span v-for="t in item.tags" :key="t" class="tag">{{ t }}</span></template>
        </div>
        <div class="detail-content">{{ item.content || '（正文为空）' }}</div>
        <div v-if="item.summary" class="card" style="margin-top:10px;background:var(--bg-panel-2);">
          <strong>摘要</strong>
          <div class="detail-content">{{ item.summary }}</div>
        </div>
        <div class="section-title">
          附件（{{ item.attachments.length }}）
          <label class="btn small">
            添加附件
            <input type="file" style="display:none" @change="addFile" />
          </label>
        </div>
        <div v-for="a in item.attachments" :key="a.id" style="margin-bottom:8px;">
          <div style="font-size:0.82rem;color:var(--text-dim);">
            <a :href="a.url" target="_blank" rel="noopener">{{ a.filename }}</a>
            · {{ a.mime_type }} · {{ fmtSize(a.size_bytes) }}
          </div>
          <img v-if="a.mime_type.startsWith('image/')" :src="a.url" class="img-att" alt="附件" />
          <audio v-else-if="a.mime_type.startsWith('audio/') || a.mime_type.includes('webm')" :src="a.url" controls />
          <a v-else :href="a.url" target="_blank" rel="noopener">下载</a>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;">
          <button class="btn small" @click="startEdit">编辑</button>
          <button class="btn small" :disabled="!!busy" @click="runSummary">
            {{ busy === 'sum' ? '生成中…' : '生成摘要' }}
          </button>
          <button class="btn small" :disabled="!!busy" @click="runTags">
            {{ busy === 'tags' ? '推荐中…' : '推荐标签' }}
          </button>
          <button class="btn small danger" :disabled="!!busy" @click="remove">
            {{ busy === 'del' ? '删除中…' : '删除' }}
          </button>
        </div>
        <div v-if="llm && !llm.configured" style="margin-top:8px;font-size:0.75rem;color:var(--text-faint);">
          LLM（{{ llm.provider }}）未配置：摘要用本地截断回退，标签推荐返回空列表。
        </div>
      </template>

      <template v-else>
        <h2>编辑知识</h2>
        <div v-if="notice" class="ok-bar">{{ notice }}</div>
        <div class="field"><label>标题</label><input v-model="draft.title" /></div>
        <div class="field"><label>正文</label><textarea v-model="draft.content" rows="10"></textarea></div>
        <div class="field"><label>项目</label>
          <select v-model="draft.project_id">
            <option value="">（无项目）</option>
            <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </div>
        <div class="field"><label>标签（逗号分隔）</label><input v-model="draft.tags" /></div>
        <div style="display:flex;gap:8px;">
          <button class="btn primary" :disabled="busy === 'save'" @click="save">
            {{ busy === 'save' ? '保存中…' : '保存' }}
          </button>
          <button class="btn" @click="editing = false">取消</button>
        </div>
      </template>
    </div>
  </div>
</template>
