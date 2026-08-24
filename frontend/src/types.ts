export interface Project {
  id: number
  name: string
  description: string
  status: 'active' | 'archived' | 'done'
  created_at: string
  updated_at: string
}

export interface Attachment {
  id: number
  knowledge_id: number
  filename: string
  mime_type: string
  size_bytes: number
  url: string
  created_at: string
}

export interface KnowledgeItem {
  id: number
  project_id: number | null
  project_name: string | null
  type: 'text' | 'voice' | 'screenshot' | 'project_note'
  title: string
  content: string
  content_preview?: string
  source: string
  tags: string[]
  summary: string | null
  created_at: string
  updated_at: string
  attachments: Attachment[]
}

export interface DashboardStats {
  today_count: number
  total_items: number
  total_projects: number
  recent_items: KnowledgeItem[]
  updated_projects: Project[]
}

export interface ProjectContext {
  project: Project
  statistics: {
    total_items: number
    by_type: Record<string, number>
    first_activity: string | null
    last_activity: string | null
  }
  timeline: { date: string; count: number }[]
  recent_items: KnowledgeItem[]
}

export interface LLMStatus {
  llm: { configured: boolean; provider: string; model: string | null }
  stt: { configured: boolean; provider: string; model: string | null }
}

export const TYPE_LABELS: Record<string, string> = {
  text: '文本',
  voice: '语音',
  screenshot: '截图',
  project_note: '项目进展',
}

export const STATUS_LABELS: Record<string, string> = {
  active: '进行中',
  archived: '已归档',
  done: '已完成',
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
