<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  getLessonsStatus, getProjectContext, getStats, listKnowledge, listProjects,
} from '../api/client'
import type { KnowledgeItem, Project } from '../types'
import { fmtTime, TYPE_LABELS } from '../types'
import { readVisits, type VisitedItem } from '../recentlyViewed'

interface ProjectCard {
  project: Project
  count: number
  recent: KnowledgeItem[]
}

const error = ref('')
const loading = ref(true)
const totals = ref({ items: 0, projects: 0, today: 0, lessons: 0 })
const cards = ref<ProjectCard[]>([])
const daily = ref<KnowledgeItem[]>([])
const lessons = ref<KnowledgeItem[]>([])
const visits = ref<VisitedItem[]>([])
const query = ref('')
const router = useRouter()

function search() {
  const q = query.value.trim()
  if (q) router.push({ name: 'search', query: { q } })
}

onMounted(async () => {
  visits.value = readVisits()
  try {
    const [stats, projects] = await Promise.all([getStats(), listProjects()])
    totals.value = {
      items: stats.total_items,
      projects: stats.total_projects,
      today: stats.today_count,
      lessons: 0,
    }

    // One list per project rather than one global feed: a project holding 272
    // book entries otherwise buries the 20 notes in every other project, which
    // is exactly what the old single "最近知识" list did.
    //
    // The context endpoint answers both questions in one request — exact count
    // and newest entries — where counting by fetching would drag a hundred full
    // records across the wire per project just to call length on them.
    const built = await Promise.all(projects.map(async (p) => {
      const ctx = await getProjectContext(p.id)
      return { project: p, count: ctx.statistics.total_items, recent: ctx.recent_items.slice(0, 4) }
    }))
    cards.value = built.sort((a, b) =>
      b.project.updated_at.localeCompare(a.project.updated_at))

    daily.value = (await listKnowledge({ limit: 30 }))
      .filter((k) => k.project_id == null).slice(0, 5)

    try {
      const [ls, recentLessons] = await Promise.all([
        getLessonsStatus(),
        listKnowledge({ tag: 'kind:lesson', limit: 4 }),
      ])
      totals.value.lessons = ls.lessons
      lessons.value = recentLessons
    } catch {
      /* lessons are optional; a KB without them still has a homepage */
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-if="error" class="error-bar">后端连接失败：{{ error }}（确认 backend 已启动）</div>

  <form class="searchbar" @submit.prevent="search">
    <input v-model="query" placeholder="搜索全部知识…" />
    <button class="btn" type="submit">搜索</button>
  </form>

  <div class="totals">
    <span><b>{{ totals.items }}</b> 条知识</span>
    <span><b>{{ totals.projects }}</b> 个项目</span>
    <span><b>{{ totals.lessons }}</b> 条教训</span>
    <span><b>{{ totals.today }}</b> 今日新增</span>
    <RouterLink class="more" to="/graph">知识图谱 →</RouterLink>
  </div>

  <p v-if="loading" class="empty">加载中…</p>

  <template v-else>
    <div class="cards">
      <div v-for="c in cards" :key="c.project.id" class="card">
        <h2>
          <RouterLink :to="`/projects/${c.project.id}`">{{ c.project.name }}</RouterLink>
          <span class="count">{{ c.count }} 条</span>
        </h2>
        <p v-if="c.project.description" class="desc">{{ c.project.description }}</p>
        <RouterLink
          v-for="k in c.recent" :key="k.id" :to="`/knowledge/${k.id}`" class="line">
          <span class="badge" :class="`type-${k.type}`">{{ TYPE_LABELS[k.type] || k.type }}</span>
          <span class="title">{{ k.title }}</span>
          <span class="when">{{ fmtTime(k.updated_at) }}</span>
        </RouterLink>
        <p v-if="!c.recent.length" class="empty">还没有条目</p>
      </div>

      <div v-if="daily.length" class="card">
        <h2>日常知识 <span class="count">无项目</span></h2>
        <RouterLink v-for="k in daily" :key="k.id" :to="`/knowledge/${k.id}`" class="line">
          <span class="badge" :class="`type-${k.type}`">{{ TYPE_LABELS[k.type] || k.type }}</span>
          <span class="title">{{ k.title }}</span>
          <span class="when">{{ fmtTime(k.updated_at) }}</span>
        </RouterLink>
      </div>
    </div>

    <div class="cards">
      <div v-if="lessons.length" class="card">
        <!-- Lessons are consulted rather than browsed, so they get their own
             entrance instead of being mixed into a general recent list. -->
        <h2>最近教训 <RouterLink class="more" to="/knowledge?tag=kind:lesson">全部 →</RouterLink></h2>
        <RouterLink v-for="k in lessons" :key="k.id" :to="`/knowledge/${k.id}`" class="line">
          <span class="title">{{ k.title }}</span>
          <span class="when">{{ fmtTime(k.updated_at) }}</span>
        </RouterLink>
      </div>

      <div v-if="visits.length" class="card">
        <h2>最近查看 <span class="count">本机记录</span></h2>
        <RouterLink v-for="v in visits" :key="v.id" :to="`/knowledge/${v.id}`" class="line">
          <span class="title">{{ v.title }}</span>
          <span class="when">{{ fmtTime(v.at) }}</span>
        </RouterLink>
      </div>
    </div>
  </template>
</template>

<style scoped>
.searchbar {
  display: flex;
  gap: 8px;
  margin: 4px 0 14px;
}
.searchbar input {
  flex: 1;
}
.totals {
  display: flex;
  gap: 20px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 0.85rem;
  color: var(--text-dim, #888);
  padding-bottom: 12px;
  margin-bottom: 16px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
}
.totals b {
  font-size: 1.15rem;
  color: var(--text, inherit);
  margin-right: 3px;
}
.totals .more {
  margin-left: auto;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}
.card h2 {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 0.98rem;
  margin: 0 0 6px;
}
.count {
  font-size: 0.74rem;
  font-weight: 400;
  color: var(--text-faint, #999);
}
.desc {
  font-size: 0.78rem;
  color: var(--text-faint, #999);
  margin: 0 0 8px;
}
.line {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 5px 0;
  border-top: 1px solid rgba(148, 163, 184, 0.14);
  text-decoration: none;
  color: inherit;
}
.line .title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.88rem;
}
.line .when {
  font-size: 0.72rem;
  color: var(--text-faint, #999);
  white-space: nowrap;
}
.line:hover .title {
  text-decoration: underline;
}
.more {
  margin-left: auto;
  font-size: 0.76rem;
  font-weight: 400;
}
.empty {
  font-size: 0.82rem;
  color: var(--text-faint, #999);
}
</style>
