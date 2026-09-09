import type {
  DashboardStats,
  KnowledgeItem,
  LLMStatus,
  Project,
  ProjectContext,
} from '../types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// KB_API_TOKEN support: only relevant when the backend has it configured
// (e.g. the public frp-exposed instance). Prompted once per browser and
// cached in localStorage; cleared on 401 so a wrong/stale token re-prompts.
function getToken(): string {
  try {
    let token = localStorage.getItem('kb_token')
    if (token == null) {
      token = window.prompt('知识库访问 Token（后端未配置鉴权可留空）') ?? ''
      localStorage.setItem('kb_token', token)
    }
    return token
  } catch {
    return ''
  }
}

function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken()
  if (!token) return fetch(input, init)
  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${token}`)
  return fetch(input, { ...init, headers })
}

async function parseError(res: Response): Promise<ApiError> {
  let detail = `HTTP ${res.status}`
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') detail = body.detail
    else if (body.detail) detail = JSON.stringify(body.detail)
  } catch {
    /* keep default */
  }
  return new ApiError(res.status, detail)
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    if (res.status === 401) {
      try {
        localStorage.removeItem('kb_token')
      } catch {
        /* ignore */
      }
    }
    throw await parseError(res)
  }
  return res.json() as Promise<T>
}

export async function getStats(): Promise<DashboardStats> {
  return json(await apiFetch('/api/stats'))
}

export async function listProjects(status?: string): Promise<Project[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return json(await apiFetch(`/api/projects${qs}`))
}

export async function createProject(name: string, description = '', status = 'active'): Promise<Project> {
  return json(await apiFetch('/api/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description, status }),
  }))
}

export async function updateProject(id: number, patch: Partial<Pick<Project, 'name' | 'description' | 'status'>>): Promise<Project> {
  return json(await apiFetch(`/api/projects/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }))
}

export async function deleteProject(id: number): Promise<Project> {
  return json(await apiFetch(`/api/projects/${id}`, { method: 'DELETE' }))
}

export async function getProjectContext(id: number): Promise<ProjectContext> {
  return json(await apiFetch(`/api/projects/${id}/context`))
}

export async function appendProjectContext(id: number, content: string, title?: string): Promise<KnowledgeItem> {
  return json(await apiFetch(`/api/projects/${id}/context/append`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, ...(title ? { title } : {}) }),
  }))
}

export interface KnowledgeQuery {
  project_id?: number | null
  type?: string
  tag?: string
  q?: string
  limit?: number
  offset?: number
}

export async function listKnowledge(query: KnowledgeQuery = {}): Promise<KnowledgeItem[]> {
  const params = new URLSearchParams()
  if (query.project_id != null) params.set('project_id', String(query.project_id))
  if (query.type) params.set('type', query.type)
  if (query.tag) params.set('tag', query.tag)
  if (query.q) params.set('q', query.q)
  params.set('limit', String(query.limit ?? 20))
  params.set('offset', String(query.offset ?? 0))
  return json(await apiFetch(`/api/knowledge?${params}`))
}

export async function getKnowledge(id: number): Promise<KnowledgeItem> {
  return json(await apiFetch(`/api/knowledge/${id}`))
}

export async function createKnowledge(fields: {
  title: string
  content: string
  type: string
  project_id?: number | null
  tags?: string[]
  source?: string
  file?: File | null
}): Promise<KnowledgeItem> {
  const form = new FormData()
  form.set('title', fields.title)
  form.set('content', fields.content)
  form.set('type', fields.type)
  if (fields.project_id != null) form.set('project_id', String(fields.project_id))
  for (const t of fields.tags ?? []) form.append('tags', t)
  if (fields.source) form.set('source', fields.source)
  if (fields.file) form.append('file', fields.file)
  return json(await apiFetch('/api/knowledge', { method: 'POST', body: form }))
}

export async function updateKnowledge(id: number, patch: {
  title?: string
  content?: string
  type?: string
  project_id?: number | null
  tags?: string[]
  summary?: string | null
}): Promise<KnowledgeItem> {
  return json(await apiFetch(`/api/knowledge/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }))
}

export async function deleteKnowledge(id: number): Promise<KnowledgeItem> {
  return json(await apiFetch(`/api/knowledge/${id}`, { method: 'DELETE' }))
}

export async function uploadAttachment(knowledgeId: number, file: File): Promise<void> {
  const form = new FormData()
  form.append('file', file)
  await json(await apiFetch(`/api/knowledge/${knowledgeId}/attachments`, { method: 'POST', body: form }))
}

export async function searchKnowledge(q: string, project_id?: number | null, type?: string, limit = 30): Promise<KnowledgeItem[]> {
  const params = new URLSearchParams({ q })
  if (project_id != null) params.set('project_id', String(project_id))
  if (type) params.set('type', type)
  params.set('limit', String(limit))
  return json(await apiFetch(`/api/search?${params}`))
}

export async function getLLMStatus(): Promise<LLMStatus> {
  return json(await apiFetch('/api/llm/status'))
}

export async function summarizeKnowledge(id: number): Promise<{ summary: string; provider: string; fallback: boolean }> {
  return json(await apiFetch('/api/llm/summarize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ knowledge_id: id }),
  }))
}

export async function suggestTags(id: number, apply = false): Promise<{ tags: string[]; provider: string; fallback: boolean }> {
  return json(await apiFetch('/api/llm/suggest-tags', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ knowledge_id: id, apply }),
  }))
}

export interface LessonsStatus {
  embedding: { configured: boolean; provider: string; model: string | null }
  lessons: number
  embedded: number
}

export async function getLessonsStatus(): Promise<LessonsStatus> {
  return json(await apiFetch('/api/lessons/status'))
}
