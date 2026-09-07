<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import ForceGraph from 'force-graph'
import { listKnowledge, listProjects } from '../api/client'

interface GraphNode {
  id: string
  label: string
  group: string
  val: number
  routeName: string
  routeId: string
}

interface GraphLink {
  source: string
  target: string
}

const TYPE_COLORS: Record<string, string> = {
  project: '#f4a261',
  text: '#4cc9f0',
  screenshot: '#f72585',
  voice: '#7209b7',
  project_note: '#90be6d',
}
const TYPE_LABELS: Record<string, string> = {
  project: '项目',
  text: '文本',
  screenshot: '截图',
  voice: '语音',
  project_note: '项目笔记',
}

const router = useRouter()
const container = ref<HTMLDivElement | null>(null)
const loading = ref(true)
const errorMsg = ref('')
let graph: ForceGraph<GraphNode, GraphLink> | null = null

function buildGraph(nodes: GraphNode[], links: GraphLink[]) {
  if (!container.value) return
  graph = new ForceGraph<GraphNode, GraphLink>(container.value)
    .graphData({ nodes, links })
    .nodeId('id')
    .nodeLabel((n) => `${n.label}`)
    .nodeVal((n) => n.val)
    .nodeColor((n) => TYPE_COLORS[n.group] ?? '#999999')
    .linkColor(() => 'rgba(148, 163, 184, 0.35)')
    .onNodeClick((n) => {
      router.push({ name: n.routeName, params: { id: n.routeId } })
    })
    .width(container.value.clientWidth)
    .height(container.value.clientHeight || 560)
}

const PAGE_SIZE = 100
const MAX_PAGES = 20 // safety cap: 2000 items is plenty for a personal KB graph

async function listAllKnowledge() {
  const all = []
  for (let page = 0; page < MAX_PAGES; page++) {
    const batch = await listKnowledge({ limit: PAGE_SIZE, offset: page * PAGE_SIZE })
    all.push(...batch)
    if (batch.length < PAGE_SIZE) break
  }
  return all
}

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const [projects, items] = await Promise.all([
      listProjects(),
      listAllKnowledge(),
    ])

    const nodes: GraphNode[] = []
    const links: GraphLink[] = []

    for (const p of projects) {
      nodes.push({
        id: `p:${p.id}`,
        label: p.name,
        group: 'project',
        val: 14,
        routeName: 'project-detail',
        routeId: String(p.id),
      })
    }

    const tagToNodeIds = new Map<string, string[]>()
    for (const item of items) {
      const nodeId = `k:${item.id}`
      nodes.push({
        id: nodeId,
        label: item.title,
        group: item.type,
        val: 5,
        routeName: 'knowledge-detail',
        routeId: String(item.id),
      })
      if (item.project_id != null) {
        links.push({ source: `p:${item.project_id}`, target: nodeId })
      }
      for (const tag of item.tags) {
        const bucket = tagToNodeIds.get(tag) ?? []
        bucket.push(nodeId)
        tagToNodeIds.set(tag, bucket)
      }
    }

    const seen = new Set<string>()
    for (const ids of tagToNodeIds.values()) {
      for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
          const key = ids[i] < ids[j] ? `${ids[i]}|${ids[j]}` : `${ids[j]}|${ids[i]}`
          if (seen.has(key)) continue
          seen.add(key)
          links.push({ source: ids[i], target: ids[j] })
        }
      }
    }

    buildGraph(nodes, links)
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => graph?._destructor())
</script>

<template>
  <div class="graph-page">
    <h1>知识图谱</h1>
    <p class="hint">节点：项目（大）/ 知识条目（小，按类型着色）。连线：项目归属 + 共享标签。点击节点跳转详情。</p>
    <p v-if="loading">加载中…</p>
    <p v-else-if="errorMsg" class="error">加载失败：{{ errorMsg }}</p>
    <div ref="container" class="graph-container"></div>
    <div class="legend">
      <span v-for="(color, key) in TYPE_COLORS" :key="key" class="legend-item">
        <span class="dot" :style="{ background: color }"></span>{{ TYPE_LABELS[key] ?? key }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.graph-page {
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 100%;
}
.hint {
  color: var(--muted, #888);
  font-size: 13px;
  margin: 0;
}
.graph-container {
  flex: 1;
  min-height: 560px;
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 8px;
  overflow: hidden;
}
.legend {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 13px;
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}
.error {
  color: #e63946;
}
</style>
