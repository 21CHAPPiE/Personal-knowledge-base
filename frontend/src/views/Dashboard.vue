<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getStats } from '../api/client'
import type { DashboardStats } from '../types'
import { fmtTime, TYPE_LABELS } from '../types'

const stats = ref<DashboardStats | null>(null)
const error = ref('')

onMounted(async () => {
  try {
    stats.value = await getStats()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})
</script>

<template>
  <h1>首页</h1>
  <div v-if="error" class="error-bar">后端连接失败：{{ error }}（确认 backend 已启动）</div>
  <template v-if="stats">
    <div class="stat-grid">
      <div class="stat"><div class="num">{{ stats.today_count }}</div><div class="label">今日新增</div></div>
      <div class="stat"><div class="num">{{ stats.total_items }}</div><div class="label">知识总数</div></div>
      <div class="stat"><div class="num">{{ stats.total_projects }}</div><div class="label">项目总数</div></div>
    </div>

    <div class="row">
      <div class="card">
        <h2>最近知识 <a class="more" href="/knowledge">全部 →</a></h2>
        <div v-if="!stats.recent_items.length" class="empty">还没有知识，点右下角 ＋ 录入</div>
        <RouterLink v-for="k in stats.recent_items" :key="k.id" :to="`/knowledge/${k.id}`" class="item">
          <div class="title-row">
            <span class="badge" :class="`type-${k.type}`">{{ TYPE_LABELS[k.type] || k.type }}</span>
            <span class="title">{{ k.title }}</span>
            <span v-if="k.project_name" class="tag">{{ k.project_name }}</span>
          </div>
          <div v-if="k.content_preview" class="preview">{{ k.content_preview }}</div>
          <div class="meta">{{ fmtTime(k.created_at) }}</div>
        </RouterLink>
      </div>

      <div class="card">
        <h2>最近更新项目 <a class="more" href="/projects">全部 →</a></h2>
        <div v-if="!stats.updated_projects.length" class="empty">还没有项目</div>
        <RouterLink v-for="p in stats.updated_projects" :key="p.id" :to="`/projects/${p.id}`" class="item">
          <div class="title-row">
            <span class="title">{{ p.name }}</span>
            <span class="badge">{{ p.status }}</span>
          </div>
          <div v-if="p.description" class="preview">{{ p.description }}</div>
          <div class="meta">更新于 {{ fmtTime(p.updated_at) }}</div>
        </RouterLink>
      </div>
    </div>
  </template>
</template>

<style scoped>
.more { font-size: 0.78rem; font-weight: 400; margin-left: auto; }
</style>
