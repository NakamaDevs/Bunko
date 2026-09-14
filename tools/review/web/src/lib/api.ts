/** Clients for the two local services the review tool talks to. */

/* Through the Aspire gateway the API shares this origin under /api. Run
 * standalone and it is a separate loopback port. */
function reviewBase(): string {
  if (import.meta.env.VITE_REVIEW_API) return import.meta.env.VITE_REVIEW_API
  return new URL('/api', location.origin).href
}

function notesBase(): string {
  if (import.meta.env.VITE_NOTES_API) return import.meta.env.VITE_NOTES_API
  return new URL('/notes', location.origin).href
}

const REVIEW_API = reviewBase()
const NOTES_API = notesBase()

export interface Repository {
  name: string
  path: string
  head: string
  dirty: boolean
  changed_files: number
}

export interface ChangedFile {
  path: string
  added: number | null
  removed: number | null
  binary: boolean
}

export interface Ref {
  name: string
  date: string
  subject: string
}

export interface Commit {
  hash: string
  author: string
  date: string
  subject: string
}

/** The statuses the file tree can decorate a row with. */
export type GitStatus = 'added' | 'deleted' | 'ignored' | 'modified' | 'renamed' | 'untracked'

export interface StatusEntry {
  path: string
  status: GitStatus
}

export interface Note {
  page_path: string
  block_preview: string
  id: number
  kind: string
  body: string
  line_number: number | null
  repo: string | null
  revision: string | null
  file_path: string | null
  resolved_at: string | null
}

async function get<T>(base: string, path: string, params: Record<string, string | undefined> = {}): Promise<T> {
  const url = new URL(base + path)
  for (const [key, value] of Object.entries(params)) {
    if (value) url.searchParams.set(key, value)
  }
  const response = await fetch(url)
  const payload = await response.json()
  if (!response.ok || payload.error) throw new Error(payload.error ?? response.statusText)
  return payload as T
}

export const review = {
  repositories: () => get<{ repositories: Repository[] }>(REVIEW_API, '/repos'),
  refs: (repo: string) =>
    get<{ branches: Ref[]; commits: Commit[]; head: string }>(REVIEW_API, `/repos/${repo}/refs`),
  changes: (repo: string, base?: string, head?: string) =>
    get<{ files: ChangedFile[] }>(REVIEW_API, `/repos/${repo}/changes`, { base, head }),
  patch: (repo: string, path: string, base?: string, head?: string) =>
    get<{ patch: string }>(REVIEW_API, `/repos/${repo}/patch`, { base, head, path }),
  blob: (repo: string, path: string, rev?: string) =>
    get<{ contents: string }>(REVIEW_API, `/repos/${repo}/blob`, { path, rev }),
  tree: (repo: string, rev?: string) =>
    get<{ paths: string[] }>(REVIEW_API, `/repos/${repo}/tree`, { rev }),
  status: (repo: string) => get<{ status: StatusEntry[] }>(REVIEW_API, `/repos/${repo}/status`),
  /** Both sides of one file, for a diff with full-file context. */
  sides: (repo: string, path: string, base?: string, head?: string) =>
    get<{ old: string | null; new: string | null }>(REVIEW_API, `/repos/${repo}/sides`, {
      path,
      base,
      head,
    }),
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(REVIEW_API + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const payload = await response.json()
  if (!response.ok || payload.error) throw new Error(payload.error ?? response.statusText)
  return payload as T
}

/** Editing. Writes land in the working tree; a commit touches only what it names. */
export const edits = {
  save: (repo: string, path: string, contents: string) =>
    post<{ path: string; bytes: number }>(`/repos/${repo}/file`, { path, contents }),
  commit: (repo: string, message: string, paths: string[]) =>
    post<{ commit: string; files: string[]; branch: string }>(`/repos/${repo}/commit`, {
      message,
      paths,
    }),
}

/** Comments live in the documentation notes service, so one worklist covers both. */
export const notes = {
  async forRepository(repo: string): Promise<Note[]> {
    try {
      const payload = await get<{ notes: Note[] }>(NOTES_API, '', { repo })
      return payload.notes
    } catch {
      return []
    }
  },
  async add(note: Record<string, unknown>): Promise<void> {
    const response = await fetch(NOTES_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(note),
    })
    await checkNoteResponse(response)
  },
  async resolve(id: number): Promise<void> {
    const response = await fetch(`${NOTES_API}/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resolved: true }),
    })
    await checkNoteResponse(response)
  },
}

export function isReachable(): Promise<boolean> {
  return fetch(`${REVIEW_API}/health`).then((r) => r.ok).catch(() => false)
}

async function checkNoteResponse(response: Response): Promise<void> {
  const payload = await response.json()
  if (!response.ok || payload.error) throw new Error(payload.error ?? response.statusText)
}
