<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ForceGraph from 'force-graph'
import { listKnowledge, listProjects, searchKnowledge } from '../api/client'
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
  kind?: string
  why?: string
  directed?: boolean
}

interface Relation {
  a: string
  b: string
  kind: string
  directed: boolean
  from: string
  to: string
  /** How the relation changed over the story; empty when it held steady. */
  arc?: string
  why: string
  shared: number
}

interface Causal {
  from: number
  to: number
  kind: string
  why: string
}

const RELATIONS_TAG = 'kind:relations'
const CAUSALITY_TAG = 'kind:causality'
// Kinds worth spotting across a crowded graph. Everything else stays neutral:
// colouring every relation type would need a legend longer than the graph is
// useful, and the ones that change how you read a story are the hostile ones.
const ADVERSARIAL = /对手|博弈|冲突|敌|对立|竞争/

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
const mode = ref<'people' | 'events' | 'all'>('people')
const minCooccurrence = ref(2)
const projectFilter = ref<number | 'all'>('all')
const projects = ref<Project[]>([])
const items = ref<KnowledgeItem[]>([])
const relations = ref<Relation[]>([])
const causal = ref<Causal[]>([])
const showLabels = ref(true)
const stats = ref({ nodes: 0, links: 0 })

// Selecting focuses instead of navigating. Clicking used to leave for the
// entry page, which meant the one question the graph exists to answer — who
// is this connected to, and how — could never be asked twice in a row.
const selected = ref<GraphNode | null>(null)
const neighbours = ref(new Set<string>())
const incident = ref(new Set<string>())
const query = ref('')
const searching = ref(false)
const hits = ref(new Set<string>())
const searchNote = ref('')

function linkEndId(end: string | { id?: string }): string {
  return typeof end === 'string' ? end : (end?.id ?? '')
}

function linkKey(l: GraphLink): string {
  return `${linkEndId(l.source)}->${linkEndId(l.target)}`
}

/** What led to the selected event, and what it set off. */
const selectedCauses = computed(() => {
  const node = selected.value
  if (!node || !node.id.startsWith('k:')) return { before: [] as Causal[], after: [] as Causal[] }
  const id = Number(node.id.slice(2))
  return {
    before: causal.value.filter((c) => c.to === id),
    after: causal.value.filter((c) => c.from === id),
  }
})

function eventTitle(id: number): string {
  return items.value.find((i) => i.id === id)?.title ?? `#${id}`
}

const selectedRelations = computed(() => {
  const node = selected.value
  if (!node || !node.id.startsWith('person:')) return []
  const name = node.id.slice('person:'.length)
  return relations.value
    .filter((r) => r.a === name || r.b === name)
    .sort((x, y) => y.shared - x.shared)
})

function focus(node: GraphNode | null) {
  selected.value = node
  const near = new Set<string>()
  const edges = new Set<string>()
  if (node && graph) {
    for (const l of graph.graphData().links as GraphLink[]) {
      const s = linkEndId(l.source)
      const t = linkEndId(l.target)
      if (s === node.id || t === node.id) {
        near.add(s === node.id ? t : s)
        edges.add(linkKey(l))
      }
    }
    near.add(node.id)
  }
  neighbours.value = near
  incident.value = edges
  // nodeCanvasObject reads these refs, so it has to be re-registered for
  // the labels to follow the new focus.
  graph?.nodeColor(nodeColor).linkColor(linkColor).nodeCanvasObject(paintNode)
}

/** Derived edge sets live one-per-item as a fenced JSON block: they are
 * inferred and regenerated wholesale, so keeping each in a single place means
 * it can be replaced without touching anything a person wrote. */
function parseDerived<T>(all: KnowledgeItem[], tag: string): T[] {
  const holder = all.find((i) => i.tags.includes(tag))
  const block = holder?.content.match(/```json\s*([\s\S]*?)```/)
  if (!block) return []
  try {
    const parsed = JSON.parse(block[1])
    return Array.isArray(parsed) ? (parsed as T[]) : []
  } catch {
    return []
  }
}
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
  // A named relation beats a co-occurrence count wherever one exists: "43
  // shared scenes" tells you two people matter to each other and nothing
  // about how, which is the whole question a reader brings to the graph.
  const named = new Set<string>()
  for (const r of relations.value) {
    if (r.shared < minCooccurrence.value) continue
    const [from, to] = r.directed && r.from && r.to ? [r.from, r.to] : [r.a, r.b]
    named.add(r.a < r.b ? `${r.a}|${r.b}` : `${r.b}|${r.a}`)
    links.push({
      source: `person:${from}`, target: `person:${to}`, weight: r.shared,
      kind: r.kind, directed: r.directed,
      why: [r.why, r.arc && `演变：${r.arc}`].filter(Boolean).join('\n'),
    })
    connected.add(r.a)
    connected.add(r.b)
  }
  for (const [key, weight] of pairs) {
    if (weight < minCooccurrence.value || named.has(key)) continue
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

/** Events, joined by what actually caused what.
 *
 * The full view connects events that share a tag, which says only "these were
 * filed alike" — following a story through it is impossible. These edges come
 * from each event's own 【因果】 resolved against its neighbours, so clicking
 * an event shows what led to it and what it set off, which is the question an
 * event raises in the first place.
 */
function buildEventGraph(): { nodes: GraphNode[]; links: GraphLink[] } {
  const byId = new Map<number, KnowledgeItem>()
  for (const item of visibleItems.value) {
    if (item.tags.includes('kind:event')) byId.set(item.id, item)
  }
  const links: GraphLink[] = []
  const touched = new Set<number>()
  for (const c of causal.value) {
    if (!byId.has(c.from) || !byId.has(c.to)) continue
    links.push({
      source: `k:${c.from}`, target: `k:${c.to}`, weight: 2,
      kind: c.kind, directed: true, why: c.why,
    })
    touched.add(c.from)
    touched.add(c.to)
  }
  const degree = new Map<number, number>()
  for (const c of causal.value) {
    degree.set(c.from, (degree.get(c.from) ?? 0) + 1)
    degree.set(c.to, (degree.get(c.to) ?? 0) + 1)
  }
  const nodes: GraphNode[] = []
  for (const [id, item] of byId) {
    // An event no chain touches has nothing to say in this view; it stays
    // reachable through search and the entry list.
    if (!touched.has(id)) continue
    nodes.push({
      id: `k:${id}`,
      label: item.title.replace(/^第.+?章\s*·\s*/, ''),
      group: item.type,
      val: 4 + (degree.get(id) ?? 0) * 2,
      routeName: 'knowledge-detail',
      routeId: String(id),
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

/** Search the corpus, then light up whoever it lands on.
 *
 * Reuses the backend's own search rather than matching node labels: asking
 * "债务" should surface the people caught up in debt events, not only a node
 * that happens to have that word in its name. In the people view a hit on an
 * event is mapped to everyone tagged in it, which is the answer the question
 * was actually about.
 */
async function runSearch() {
  const q = query.value.trim()
  hits.value = new Set()
  searchNote.value = ''
  if (!q) {
    graph?.nodeColor(nodeColor).nodeCanvasObject(paintNode)
    return
  }
  searching.value = true
  try {
    const found = await searchKnowledge(q, null, undefined, 60)
    const ids = new Set<string>()
    for (const item of found) {
      if (projectFilter.value !== 'all' && item.project_id !== projectFilter.value) continue
      ids.add(`k:${item.id}`)
      if (mode.value === 'people') for (const p of personsOf(item)) ids.add(`person:${p}`)
    }
    const present = new Set((graph?.graphData().nodes as GraphNode[] | undefined)?.map((n) => n.id) ?? [])
    hits.value = new Set(Array.from(ids).filter((id) => present.has(id)))
    searchNote.value = hits.value.size
      ? `命中 ${found.length} 条内容，落在图上 ${hits.value.size} 个节点`
      : `命中 ${found.length} 条内容，但都不在当前视图里`
    graph?.nodeColor(nodeColor).nodeCanvasObject(paintNode)
  } catch (e) {
    searchNote.value = e instanceof Error ? e.message : String(e)
  } finally {
    searching.value = false
  }
}

/** Muted unless it is the focus, a neighbour of it, or a search hit. Dimming
 * the rest rather than hiding it keeps the shape of the whole visible while
 * the answer to "what is this connected to" stands out of it. */
function nodeColor(n: GraphNode): string {
  const base = TYPE_COLORS[n.group] ?? '#999999'
  if (hits.value.size && hits.value.has(n.id)) return '#facc15'
  const focused = neighbours.value.size > 0
  if (focused && !neighbours.value.has(n.id)) return 'rgba(148, 163, 184, 0.15)'
  if (selected.value?.id === n.id) return '#ffffff'
  return base
}

function linkColor(l: GraphLink): string {
  if (incident.value.size) {
    // The focused edges are the answer to the question just asked, so they
    // get a colour of their own rather than merely being less faded than the
    // rest; everything else drops to a hint of structure.
    return incident.value.has(linkKey(l))
      ? (l.kind && ADVERSARIAL.test(l.kind) ? '#f87171' : '#38bdf8')
      : 'rgba(148, 163, 184, 0.10)'
  }
  return l.kind && ADVERSARIAL.test(l.kind)
    ? 'rgba(230, 90, 80, 0.55)'
    : l.kind ? 'rgba(148, 163, 184, 0.55)' : 'rgba(148, 163, 184, 0.22)'
}

/** Paint a node's name onto the canvas.
 *
 * Once something is focused, only it and what it connects to keep their
 * names. Dimming the dots was never enough on its own — every label stayed at
 * full brightness, and 592 names at once is the whole reason the view read as
 * a smear rather than a graph.
 */
function paintNode(n: GraphNode, ctx: CanvasRenderingContext2D, scale: number) {
  if (!showLabels.value) return
  const focused = neighbours.value.size > 0
  if (focused && !neighbours.value.has(n.id)) return
  if (!focused && hits.value.size && !hits.value.has(n.id)) return
  // Zoomed out with nothing focused, only the hubs keep their labels.
  if (!focused && !hits.value.size && scale < 1.2 && n.val < 8) return
  const size = Math.max(10 / scale, 2.2)
  ctx.font = `${size}px system-ui, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  const y = (n as unknown as { y: number }).y + Math.sqrt(n.val) * 1.6
  const x = (n as unknown as { x: number }).x
  ctx.lineWidth = 2.5 / scale
  ctx.strokeStyle = 'rgba(15, 23, 42, 0.85)'
  ctx.strokeText(n.label, x, y)
  ctx.fillStyle = focused && selected.value?.id === n.id ? '#ffffff' : '#e2e8f0'
  ctx.fillText(n.label, x, y)
}

function render() {
  if (!container.value) return
  const { nodes, links } = mode.value === 'people' ? buildPeopleGraph()
    : mode.value === 'events' ? buildEventGraph() : buildAllGraph()
  stats.value = { nodes: nodes.length, links: links.length }
  if (!graph) graph = new ForceGraph<GraphNode, GraphLink>(container.value)
  graph
    .graphData({ nodes, links })
    .nodeId('id')
    .nodeLabel((n) => n.label)
    .nodeVal((n) => n.val)
    .nodeColor(nodeColor)
    .linkColor(linkColor)
    // Thickness carries the count, so a strong pairing reads as strong rather
    // than looking the same as a single shared scene.
    .linkWidth((l) => Math.min(0.5 + l.weight / 3, 6))
    .linkDirectionalArrowLength((l) => (l.directed ? 4 : 0))
    .linkDirectionalArrowRelPos(1)
    .linkLabel((l) => (l.kind ? `${l.kind}（同框 ${l.weight} 次）\n${l.why ?? ''}` : `同框 ${l.weight} 次`))
    // Names painted onto the canvas rather than left to the hover tooltip.
    // Having to point at a node to learn who it is makes the graph unusable
    // for the thing it is for — seeing the shape of the whole at once.
    .nodeCanvasObjectMode(() => 'after')
    .nodeCanvasObject(paintNode)
    .linkCanvasObjectMode(() => 'after')
    .linkCanvasObject((l, ctx, scale) => {
      // Only once there is room: relation names at overview zoom overlap into
      // noise, and the arrow already carries direction at that distance.
      if (!showLabels.value || !l.kind || scale < 1.6) return
      const s = l.source as unknown as { x: number; y: number }
      const t = l.target as unknown as { x: number; y: number }
      if (!s?.x || !t?.x) return
      const size = Math.max(9 / scale, 2)
      ctx.font = `${size}px system-ui, sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      const x = (s.x + t.x) / 2
      const y = (s.y + t.y) / 2
      const pad = size * 0.4
      const w = ctx.measureText(l.kind).width
      ctx.fillStyle = 'rgba(15, 23, 42, 0.82)'
      ctx.fillRect(x - w / 2 - pad, y - size / 2 - pad / 2, w + pad * 2, size + pad)
      ctx.fillStyle = ADVERSARIAL.test(l.kind) ? '#fca5a5' : '#cbd5e1'
      ctx.fillText(l.kind, x, y)
    })
    // First tap on a node focuses it (highlights its edges, opens the side
    // panel) without leaving the graph. A second tap on that same
    // already-focused node is the reader saying "no really, open it" — that
    // one navigates to the full item. Tapping empty background is the way
    // back out, at either stage.
    .onNodeClick((n) => {
      if (selected.value?.id === n.id) router.push({ name: n.routeName, params: { id: n.routeId } })
      else focus(n)
    })
    .onBackgroundClick(() => focus(null))
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
    relations.value = parseDerived<Relation>(all, RELATIONS_TAG)
    causal.value = parseDerived<Causal>(all, CAUSALITY_TAG)
    render()
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

watch([mode, minCooccurrence, projectFilter, showLabels], () => {
  if (loading.value) return
  // The old focus points at nodes this view may not contain.
  focus(null)
  hits.value = new Set()
  searchNote.value = ''
  render()
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
        <button :class="{ on: mode === 'events' }" @click="mode = 'events'">事件因果</button>
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

      <label>
        <input v-model="showLabels" type="checkbox" /> 显示名称
      </label>

      <span class="counts">
        {{ stats.nodes }} 节点 / {{ stats.links }} 连线<template
          v-if="mode === 'people' && relations.length"> · {{ relations.length }} 条具名关系</template><template
          v-else-if="mode === 'events' && causal.length"> · {{ causal.length }} 条因果关系</template>
      </span>
    </div>

    <p class="hint">
      <template v-if="mode === 'people'">
        只画人物。<b>有名字的连线</b>是从两人真正互动过的事件里推断出的关系，箭头表示方向（如债权人指向债务人）；
        <b>红色</b>是对抗性关系。灰色细线是还没命名的、仅有共现的连接。放大后会显示关系名，鼠标停在线上看依据和演变。
      </template>
      <template v-else-if="mode === 'events'">
        只画事件，箭头是<b>因果</b>：A → B 表示 A 直接导致了 B。点一个事件，会highlight它的前因和后果。
        没有被任何因果链连到的事件不画（它们在搜索和列表里仍能找到）。
      </template>
      <template v-else>
        全部条目。已剔除「项目归属」和「章节」这类分类连线——它们只说明归属，不代表内容相关。
      </template>
    </p>

    <form class="searchbar" @submit.prevent="runSearch">
      <input v-model="query" placeholder="在图谱里搜索，命中的节点会高亮…" />
      <button class="btn" type="submit" :disabled="searching">
        {{ searching ? '搜索中…' : '搜索' }}
      </button>
      <button v-if="hits.size || query" class="btn" type="button"
              @click="query = ''; runSearch()">清除</button>
      <span v-if="searchNote" class="note">{{ searchNote }}</span>
    </form>

    <div v-if="selected" class="focus-panel">
      <div class="focus-head">
        <b>{{ selected.label }}</b>
        <span class="note">{{ neighbours.size - 1 }} 个直接关联</span>
        <button class="btn small" @click="router.push({ name: selected.routeName, params: { id: selected.routeId } })">
          打开条目 →
        </button>
        <button class="btn small" @click="focus(null)">取消聚焦</button>
      </div>
      <ul v-if="selectedCauses.before.length || selectedCauses.after.length" class="rel-list">
        <li v-for="c in selectedCauses.before" :key="'b' + c.from">
          <span class="rel-kind">前因 · {{ c.kind }}</span>{{ eventTitle(c.from) }}
          <div class="note why">{{ c.why }}</div>
        </li>
        <li v-for="c in selectedCauses.after" :key="'a' + c.to">
          <span class="rel-kind after">后果 · {{ c.kind }}</span>{{ eventTitle(c.to) }}
          <div class="note why">{{ c.why }}</div>
        </li>
      </ul>
      <ul v-else-if="selectedRelations.length" class="rel-list">
        <li v-for="r in selectedRelations" :key="r.a + r.b">
          <span class="rel-kind" :class="{ bad: ADVERSARIAL.test(r.kind) }">{{ r.kind }}</span>
          {{ r.a === selected.label ? r.b : r.a 
          }}<span v-if="r.directed" class="note">（{{ r.from }} → {{ r.to }}）</span>
          <span class="note"> · 互动 {{ r.shared }} 次</span>
          <div class="note why">{{ r.why }}<template v-if="r.arc"><br />演变：{{ r.arc }}</template></div>
        </li>
      </ul>
      <p v-else class="note">这个节点还没有具名关系，只有共现连接。</p>
    </div>

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
.searchbar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.searchbar input {
  flex: 1;
  min-width: 200px;
}
.note {
  color: var(--text-dim, #8a94a6);
  font-size: 12px;
}
.focus-panel {
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 8px;
  padding: 10px 12px;
  max-height: 190px;
  overflow-y: auto;
}
.focus-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.focus-head .btn {
  margin-left: auto;
}
.focus-head .btn + .btn {
  margin-left: 0;
}
.rel-list {
  margin: 0;
  padding-left: 0;
  list-style: none;
  display: grid;
  gap: 7px;
}
.rel-kind {
  display: inline-block;
  padding: 1px 7px;
  margin-right: 6px;
  border-radius: 4px;
  font-size: 12px;
  background: rgba(148, 163, 184, 0.18);
}
.rel-kind.after {
  background: rgba(144, 190, 109, 0.22);
  color: #bbf7d0;
}
.rel-kind.bad {
  background: rgba(230, 90, 80, 0.22);
  color: #fca5a5;
}
.why {
  margin-top: 2px;
  line-height: 1.5;
}
</style>
