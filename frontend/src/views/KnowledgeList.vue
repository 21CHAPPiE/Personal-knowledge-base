<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listKnowledge, listProjects } from '../api/client'
import type { KnowledgeItem, Project } from '../types'
import { fmtTime, TYPE_LABELS } from '../types'

const items = ref<KnowledgeItem[]>([])
const projects = ref<Project[]>([])
const type = ref('')
const tag = ref('')
const project = ref<number | ''>('')
const error = ref('')
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const [k] = await Promise.all([
      listKnowledge({
        type: type.value || undefined,
        tag: tag.value || undefined,
        project_id: project.value === '' ? null : Number(project.value),
      }),
      listProjects().then((p) => (projects.value = p)).catch(() => undefined),
    ])
    items.value = k
    error.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <h1>知识</h1>
  <div class="card" style="display:flex;gap:8px;flex-wrap:wrap;">
    <select v-model="type" @change="load" style="max-width:130px">
      <option value="">全部类型</option>
      <option value="text">文本</option>
      <option value="voice">语音</option>
      <option value="screenshot">截图</option>
      <option value="project_note">项目进展</option>
    </select>
    <input v-model="tag" @keyup.enter="load" placeholder="标签过滤" style="max-width:140px" />
    <select v-model="project" @change="load" style="max-width:150px">
      <option value="">全部项目</option>
      <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
    </select>
    <button class="btn small" @click="load">{{ loading ? '加载中…' : '过滤' }}</button>
  </div>
  <div v-if="error" class="error-bar">{{ error }}</div>
  <div v-if="!items.length && !loading" class="empty">没有符合条件的知识</div>
  <RouterLink v-for="k in items" :key="k.id" :to="`/knowledge/${k.id}`" class="item">
    <div class="title-row">
      <span class="badge" :class="`type-${k.type}`">{{ TYPE_LABELS[k.type] || k.type }}</span>
      <span class="title">{{ k.title }}</span>
      <span v-for="t in k.tags" :key="t" class="tag">{{ t }}</span>
    </div>
    <div v-if="k.content_preview" class="preview">{{ k.content_preview }}</div>
    <div class="meta">
      {{ fmtTime(k.updated_at) }}
      <template v-if="k.project_name"> · {{ k.project_name }}</template>
      <template v-if="k.attachments.length"> · {{ k.attachments.length }} 个附件</template>
    </div>
  </RouterLink>
</template>
