/** What this browser opened lately, newest first.
 *
 * Per-viewer and per-browser by design — which entries you keep coming back to
 * is your own trail, not a fact about the knowledge base, so it stays in
 * localStorage rather than becoming a row everyone shares.
 */

const KEY = 'kb_recent_views'
const LIMIT = 8

export interface VisitedItem {
  id: number
  title: string
  at: string
}

export function recordVisit(id: number, title: string): void {
  try {
    const list = readVisits().filter((v) => v.id !== id)
    list.unshift({ id, title, at: new Date().toISOString() })
    localStorage.setItem(KEY, JSON.stringify(list.slice(0, LIMIT)))
  } catch {
    /* private mode, blocked storage: a missing trail is not worth an error */
  }
}

export function readVisits(): VisitedItem[] {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((v) => v && typeof v.id === 'number') : []
  } catch {
    return []
  }
}
