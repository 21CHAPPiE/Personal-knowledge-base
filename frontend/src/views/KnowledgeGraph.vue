<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ForceGraph from 'force-graph'
import { listKnowledge, listProjects } from '../api/client'
import type { KnowledgeItem, Project } from '../types'

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
  weight: number
}

const TYPE_COLORS: Record<string, string> = {
  person: '#e07a5f',
  project: '#f4a261',
  text: '#4cc9f0',
  screenshot: '#f72585',
  voice: '#7209b7',
  project_note: '#90be6d',
}
const TYPE_LABELS: Record<string, string> = {
  person: '人物',
  project: '项目',
  text: '文本',
  screenshot: '截图',
  voice: '语音',
  project_note: '项目笔记',
}

// Tags that classify an entry rather than relate it to another one. Two lessons
// both tagged kind:lesson, or both recorded on 设备:X99, have nothing to do with
// each other — drawing that edge is noise, and since these sit on nearly every
// entry it is the noise that swamps the graph.
const CLASSIFICATION_PREFIXES = ['kind:', 'scope:', 'os:', 'not:', 'machine:', 'cost:', '设备:',
                                 '作品:', '章节:']
const MAX_TAG_FANOUT = 12
const PERSON_PREFIX = '人物:'

function isClassificationTag(tag: string): boolean {
  return CLASSIFICATION_PREFIXES.some((p) => tag.startsWith(p)) || tag.startsWith(PERSON_PREFIX)
}

const router = useRouter()
const container = ref<HTMLDivElement | null>(null)
const loading = ref(true)
const errorMsg = ref('')
const mode = ref<'people' | 'all'>('people')
const minCooccurrence = ref(2)
const projectFilter = ref<number | 'all'>('all')
const projects = ref<Project[]>([])
const items = ref<KnowledgeItem[]>([])
const stats = ref({ nodes: 0, links: 0 })
let graph: ForceGraph<GraphNode, GraphLink> | null = null

const visibleItems = computed(() =>
  projectFilter.value === 'all'
    ? items.value
    : items.value.filter((i) => i.project_id === projectFilter.value))

function personsOf(item: KnowledgeItem): string[] {
  return item.tags.filter((t) => t.startsWith(PERSON_PREFIX)).map((t) => t.slice(PERSON_PREFIX.length))
}

/** People only, joined by how often they appear in the same event.
 *
 * The event-centred view drowns: 293 event nodes each tethered to its project
 * and to everyone in it is 1,120 edges, and no layout rescues that. Dropping
 * events and asking instead "who shows up with whom" is the graph the question
 * "以人物关系展开" was actually about — 91 nodes, and at a threshold of 2
 * roughly 100 edges.
 */
function buildPeopleGraph(): { nodes: GraphNode[]; links: GraphLink[] } {
  const entryId = new Map<string, number>()
  for (const item of visibleItems.value) {
    if (item.tags.includes('kind:person')) entryId.set(item.title.trim(), item.id)
  }
  const appearances = new Map<string, number>()
  const pairs = new Map<string, number>()
  for (const item of visibleItems.value) {
    const people = Array.from(new Set(personsOf(item)))
    for (const p of people) appearances.set(p, (appearances.get(p) ?? 0) + 1)
    if (!item.tags.includes('kind:event')) continue
    for (let i = 0; i < people.length; i++) {
      for (let j = i + 1; j < people.length; j++) {
        const key = people[i] < people[j] ? `${people[i]}|${people[j]}` : `${people[j]}|${people[i]}`
        pairs.set(key, (pairs.get(key) ?? 0) + 1)
      }
    }
  }

  const links: GraphLink[] = []
  const connected = new Set<string>()
  for (const [key, weight] of pairs) {
    if (weight < minCooccurrence.value) continue
    const [a, b] = key.split('|')
    links.push({ source: `person:${a}`, target: `person:${b}`, weight })
    connected.add(a)
    connected.add(b)
  }

  const nodes: GraphNode[] = []
  for (const [name, count] of appearances) {
    // An isolated node at a high threshold is noise, not information; the
    // person is still reachable through search and the entry list.
    if (!connected.has(name) && minCooccurrence.value > 1) continue
    const id = entryId.get(name)
    nodes.push({
      id: `person:${name}`,
      label: name,
      group: 'person',
      val: Math.min(4 + count / 4, 20),
      routeName: id != null ? 'knowledge-detail' : 'search',
      routeId: id != null ? String(id) : name,
    })
  }
  return { nodes, links }
}

/** Everything, minus the edges that carry no information.
 *
 * Project containment was 283 of the old 1,120 edges and drew every entry into
 * one star; 章节: tags added 268 more saying only "same chapter". Both are
 * classification, not relation, so the full view now shows topical links only.
 */
function buildAllGraph(): { nodes: GraphNode[]; links: GraphLink[] } {
  const nodes: GraphNode[] = []
  const links: GraphLink[] = []
  const entryId = new Map<string, number>()
  for (const item of visibleItems.value) {
    if (item.tags.includes('kind:person')) entryId.set(item.title.trim(), item.id)
  }
  const personNode = new Map<string, string>()
  for (const item of visibleItems.value) {
    for (const name of personsOf(item)) {
      if (personNode.has(name)) continue
      const id = entryId.get(name)
      personNode.set(name, id != null ? `k:${id}` : `person:${name}`)
    }
  }
  for (const [name, nodeId] of personNode) {
    if (nodeId.startsWith('k:')) continue
    nodes.push({ id: nodeId, label: name, group: 'person', val: 10, routeName: 'search', routeId: name })
  }

  const tagToNodes = new Map<string, string[]>()
  for (const item of visibleItems.value) {
    const nodeId = `k:${item.id}`
    const isPerson = item.tags.includes('kind:person')
    nodes.push({
      id: nodeId,
      label: item.title,
      group: isPerson ? 'person' : item.type,
      val: isPerson ? 10 : 5,
      routeName: 'knowledge-detail',
      routeId: String(item.id),
    })
    for (const tag of item.tags) {
      if (tag.startsWith(PERSON_PREFIX)) {
        const target = personNode.get(tag.slice(PERSON_PREFIX.length))
        if (target && target !== nodeId) links.push({ source: nodeId, target, weight: 1 })
        continue
      }
      if (isClassificationTag(tag)) continue
      const bucket = tagToNodes.get(tag) ?? []
      bucket.push(nodeId)
      tagToNodes.set(tag, bucket)
    }
  }

  const seen = new Set<string>()
  for (const ids of tagToNodes.values()) {
    if (ids.length > MAX_TAG_FANOUT) continue
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const key = ids[i] < ids[j] ? `${ids[i]}|${ids[j]}` : `${ids[j]}|${ids[i]}`
        if (seen.has(key)) continue
        seen.add(key)
        links.push({ source: ids[i], target: ids[j], weight: 1 })
      }
    }
  }
  return { nodes, links }
}

function render() {
  if (!container.value) return
  const { nodes, links } = mode.value === 'people' ? buildPeopleGraph() : buildAllGraph()
  stats.value = { nodes: nodes.length, links: links.length }
  if (!graph) graph = new ForceGraph<GraphNode, GraphLink>(container.value)
  graph
    .graphData({ nodes, links })
    .nodeId('id')
    .nodeLabel((n) => n.label)
    .nodeVal((n) => n.val)
    .nodeColor((n) => TYPE_COLORS[n.group] ?? '#999999')
    .linkColor(() => 'rgba(148, 163, 184, 0.35)')
    // Thickness carries the count, so a strong pairing reads as strong rather
    // than looking the same as a single shared scene.
    .linkWidth((l) => Math.min(0.5 + l.weight / 3, 6))
    .onNodeClick((n) => router.push({ name: n.routeName, params: { id: n.routeId } }))
    .width(container.value.clientWidth)
    .height(container.value.clientHeight || 560)
}

const PAGE_SIZE = 100
const MAX_PAGES = 20

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const all: KnowledgeItem[] = []
    for (let page = 0; page < MAX_PAGES; page++) {
      const batch = await listKnowledge({ limit: PAGE_SIZE, offset: page * PAGE_SIZE })
      all.push(...batch)
      if (batch.length < PAGE_SIZE) break
    }
    projects.value = await listProjects()
    items.value = all
    render()
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

watch([mode, minCooccurrence, projectFilter], () => {
  if (!loading.value) render()
})

onMounted(load)
onBeforeUnmount(() => graph?._destructor())
</script>

<template>
  <div class="graph-page">
    <h1>知识图谱</h1>

    <div class="controls">
      <span class="seg">
        <button :class="{ on: mode === 'people' }" @click="mode = 'people'">人物关系</button>
        <button :class="{ on: mode === 'all' }" @click="mode = 'all'">全部条目</button>
      </span>

      <label>
        项目
        <select v-model="projectFilter">
          <option value="all">全部</option>
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </label>

      <label v-if="mode === 'people'">
        共现次数 ≥ {{ minCooccurrence }}
        <input v-model.number="minCooccurrence" type="range" min="1" max="8" />
      </label>

      <span class="counts">{{ stats.nodes }} 节点 / {{ stats.links }} 连线</span>
    </div>

    <p class="hint">
      <template v-if="mode === 'people'">
        只画人物，连线表示两人同时出现在多少个事件里，线越粗关系越紧密。拖动滑块可只看主要关系。
      </template>
      <template v-else>
        全部条目。已剔除「项目归属」和「章节」这类分类连线——它们只说明归属，不代表内容相关。
      </template>
    </p>

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
.controls {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 13px;
}
.controls label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.seg button {
  padding: 4px 12px;
  border: 1px solid rgba(148, 163, 184, 0.4);
  background: transparent;
  color: inherit;
  cursor: pointer;
}
.seg button:first-child {
  border-radius: 6px 0 0 6px;
}
.seg button:last-child {
  border-radius: 0 6px 6px 0;
  border-left: none;
}
.seg button.on {
  background: #e07a5f;
  border-color: #e07a5f;
  color: #fff;
}
.counts {
  margin-left: auto;
  color: var(--text-dim, #888);
  font-variant-numeric: tabular-nums;
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
