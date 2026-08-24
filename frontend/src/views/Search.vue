<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listProjects, searchKnowledge } from '../api/client'
import type { KnowledgeItem, Project } from '../types'
import { fmtTime, TYPE_LABELS } from '../types'

const route = useRoute()
const router = useRouter()
const q = ref('')
const type = ref('')
const project = ref<number | ''>('')
const projects = ref<Project[]>([])
const results = ref<KnowledgeItem[] | null>(null)
const searched = ref(false)
const error = ref('')

onMounted(async () => {
  const initial = typeof route.query.q === 'string' ? route.query.q : ''
  q.value = initial
  try {
    projects.value = await listProjects()
  } catch {
    /* optional */
  }
  if (initial) await doSearch()
})

async function doSearch() {
  if (!q.value.trim()) return
  searched.value = true
  error.value = ''
  router.replace({ query: { q: q.value.trim() } })
  try {
    results.value = await searchKnowledge(
      q.value.trim(),
      project.value === '' ? null : Number(project.value),
      type.value || undefined,
    )
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    results.value = []
  }
}
</script>

<template>
  <h1>搜索</h1>
  <div class="search-box">
    <input v-model="q" @keyup.enter="doSearch" placeholder="搜索标题 / 正文 / 标签，支持中文子串" />
    <select v-model="type" style="max-width:120px;">
      <option value="">全部类型</option>
      <option value="text">文本</option>
      <option value="voice">语音</option>
      <option value="screenshot">截图</option>
      <option value="project_note">项目进展</option>
    </select>
    <select v-model="project" style="max-width:140px;">
      <option value="">全部项目</option>
      <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
    </select>
    <button class="btn primary" @click="doSearch">搜索</button>
  </div>

  <div v-if="error" class="error-bar">{{ error }}</div>
  <div v-if="searched && results && !results.length" class="empty">没有匹配结果</div>
  <div v-if="searched && results" style="font-size:0.8rem;color:var(--text-faint);margin-bottom:8px;">
    共 {{ results.length }} 条结果
  </div>
  <RouterLink v-for="k in results ?? []" :key="k.id" :to="`/knowledge/${k.id}`" class="item">
    <div class="title-row">
      <span class="badge" :class="`type-${k.type}`">{{ TYPE_LABELS[k.type] || k.type }}</span>
      <span class="title">{{ k.title }}</span>
      <span v-if="k.project_name" class="tag">{{ k.project_name }}</span>
    </div>
    <div v-if="k.content_preview" class="preview">{{ k.content_preview }}</div>
    <div class="meta">{{ fmtTime(k.updated_at) }}</div>
  </RouterLink>
</template>
