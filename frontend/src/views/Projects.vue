<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { createProject, deleteProject, listProjects } from '../api/client'
import type { Project } from '../types'
import { fmtTime, STATUS_LABELS } from '../types'

const projects = ref<Project[]>([])
const name = ref('')
const description = ref('')
const error = ref('')
const busy = ref(false)

async function load() {
  try {
    projects.value = await listProjects()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(load)

async function create() {
  if (busy.value || !name.value.trim()) return
  busy.value = true
  try {
    await createProject(name.value.trim(), description.value.trim())
    name.value = ''
    description.value = ''
    error.value = ''
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

async function remove(p: Project) {
  if (!confirm(`删除项目「${p.name}」？项目下的知识会保留但不再归属该项目。`)) return
  try {
    await deleteProject(p.id)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}
</script>

<template>
  <h1>项目</h1>
  <div class="card">
    <div class="field"><label>项目名</label><input v-model="name" @keyup.enter="create" placeholder="例如：个人知识库" /></div>
    <div class="field"><label>简介（可选）</label><textarea v-model="description" rows="2" placeholder="这个项目的目标…"></textarea></div>
    <button class="btn primary" :disabled="busy || !name.trim()" @click="create">
      {{ busy ? '创建中…' : '新建项目' }}
    </button>
  </div>
  <div v-if="error" class="error-bar">{{ error }}</div>
  <div v-if="!projects.length" class="empty">还没有项目</div>
  <div v-for="p in projects" :key="p.id" class="card">
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
      <RouterLink :to="`/projects/${p.id}`" class="title" style="font-weight:600;font-size:1.02rem;">{{ p.name }}</RouterLink>
      <span class="badge">{{ STATUS_LABELS[p.status] || p.status }}</span>
      <button class="btn small danger" style="margin-left:auto;" @click="remove(p)">删除</button>
    </div>
    <div v-if="p.description" class="preview" style="color:var(--text-dim);font-size:0.85rem;margin-top:4px;">{{ p.description }}</div>
    <div class="meta" style="color:var(--text-faint);font-size:0.75rem;margin-top:4px;">
      创建于 {{ fmtTime(p.created_at) }} · 更新于 {{ fmtTime(p.updated_at) }}
    </div>
  </div>
</template>
