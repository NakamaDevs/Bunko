<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { GitBranch, RefreshCw, Columns2, Rows2, Moon, Sun, FileDiff, FolderTree, Pencil, GitCommitHorizontal } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import DiffPane from '@/components/DiffPane.vue'
import FileTreePane from '@/components/FileTreePane.vue'
import FilePane from '@/components/FilePane.vue'
import {
  review,
  notes,
  edits,
  type ChangedFile,
  type Note,
  type Ref,
  type Repository,
  type StatusEntry,
} from '@/lib/api'

const repositories = ref<Repository[]>([])
const repo = ref('')
const branches = ref<Ref[]>([])
const base = ref('')
const head = ref('')
const files = ref<ChangedFile[]>([])
const selected = ref('')
const oldText = ref<string | null>(null)
const newText = ref<string | null>(null)
const repoNotes = ref<Note[]>([])
const split = ref(true)
const dark = ref(false)
const loading = ref(false)
const problem = ref('')

/* The line a comment is being written against, and its draft. */
const pendingLine = ref<number | null>(null)
const draft = ref('')
const draftKind = ref('NOTE')
const KINDS = ['NOTE', 'TODO', 'QUESTION', 'FIXME']

/* "changes" reviews a range; "files" browses the whole revision. */
const mode = ref<'changes' | 'files'>('changes')
const treePaths = ref<string[]>([])
const treeStatus = ref<StatusEntry[]>([])
const fileText = ref<string | null>(null)

/* Editing is off unless asked for: the tool is for reading code, and a stray
 * keystroke should not change a file. */
const editing = ref(false)
const drafts = ref(new Map<string, string>())
const commitMessage = ref('')
const committed = ref('')

const dirtyPaths = computed(() => [...drafts.value.keys()].sort())

const filePane = ref<{ revealLine: (line: number) => boolean } | null>(null)

/* The text another tool asked to be shown, resolved to a line once the file is
 * loaded. Matching text rather than a line number survives edits above it. */
function lineOf(contents: string, match: string): number {
  const needle = match.trim().toLowerCase()
  if (!needle) return 0
  const lines = contents.split('\n')
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].toLowerCase().includes(needle)) return i + 1
  }
  return 0
}

const current = computed(() => repositories.value.find((entry) => entry.name === repo.value))
const comparing = computed(() => Boolean(base.value && head.value))

/** Comments still open on the file being viewed. */
const fileNotes = computed(() =>
  repoNotes.value.filter((note) => note.file_path === selected.value && !note.resolved_at),
)

function countFor(path: string) {
  return repoNotes.value.filter((note) => note.file_path === path && !note.resolved_at).length
}

async function guard<T>(work: () => Promise<T>) {
  loading.value = true
  problem.value = ''
  try {
    return await work()
  } catch (error) {
    problem.value = error instanceof Error ? error.message : String(error)
    return undefined
  } finally {
    loading.value = false
  }
}

async function loadRepositories() {
  const payload = await guard(() => review.repositories())
  if (!payload) return
  repositories.value = payload.repositories
  if (!repo.value) {
    const dirty = payload.repositories.find((entry) => entry.dirty)
    repo.value = (dirty ?? payload.repositories[0])?.name ?? ''
  }
}

async function loadRepository() {
  if (!repo.value) return
  files.value = []
  treePaths.value = []
  selected.value = ''
  const refs = await guard(() => review.refs(repo.value))
  branches.value = refs?.branches ?? []
  repoNotes.value = await notes.forRepository(repo.value)
  await (mode.value === 'files' ? loadTree() : loadChanges())
}

async function loadTree() {
  const [paths, status] = await Promise.all([
    guard(() => review.tree(repo.value, head.value || 'WORKTREE')),
    guard(() => review.status(repo.value)),
  ])
  treePaths.value = paths?.paths ?? []
  treeStatus.value = status?.status ?? []
}

async function openFile(path: string) {
  selected.value = path
  pendingLine.value = null
  committed.value = ''
  const draft = drafts.value.get(path)
  if (draft !== undefined) {
    fileText.value = draft
    return
  }
  const payload = await guard(() =>
    review.blob(repo.value, path, head.value || 'WORKTREE'),
  )
  fileText.value = payload?.contents ?? null
}

/* An edit is held until it is saved, so leaving a file does not write it. */
function recordDraft(contents: string) {
  drafts.value.set(selected.value, contents)
  drafts.value = new Map(drafts.value)
}

async function saveDrafts() {
  for (const [path, contents] of drafts.value) {
    const saved = await guard(() => edits.save(repo.value, path, contents))
    if (!saved) return false
  }
  return true
}

async function saveWorkingTree() {
  if (await saveDrafts()) {
    committed.value = `Saved ${dirtyPaths.value.length} file(s) to the working tree`;
  }
}

async function commitDrafts() {
  if (!commitMessage.value.trim() || !dirtyPaths.value.length) return
  if (!(await saveDrafts())) return
  const paths = dirtyPaths.value
  const result = await guard(() => edits.commit(repo.value, commitMessage.value, paths))
  if (!result) return
  committed.value = `Committed ${result.commit} on ${result.branch}: ${result.files.length} file(s)`
  drafts.value = new Map()
  commitMessage.value = ''
  await loadChanges()
}

function discardDrafts() {
  drafts.value = new Map()
  commitMessage.value = ''
  if (selected.value) openFile(selected.value)
}

async function switchMode(next: 'changes' | 'files') {
  if (mode.value === next) return
  mode.value = next
  selected.value = ''
  fileText.value = null
  await (next === 'files' ? loadTree() : loadChanges())
}

async function loadChanges() {
  const payload = await guard(() => review.changes(repo.value, base.value, head.value))
  files.value = payload?.files ?? []
  if (files.value.length) await open(files.value[0].path)
}

async function open(path: string) {
  selected.value = path
  pendingLine.value = null
  const payload = await guard(() => review.sides(repo.value, path, base.value, head.value))
  oldText.value = payload?.old ?? null
  newText.value = payload?.new ?? null
}

function startComment(line: number) {
  pendingLine.value = line
  draft.value = ''
  draftKind.value = 'NOTE'
}

function cancelComment() {
  pendingLine.value = null
  draft.value = ''
}

async function saveComment() {
  const line = pendingLine.value
  const body = draft.value.trim()
  if (line === null || !body) return
  await notes.add({
    page_path: `review:${repo.value}`,
    page_title: `${repo.value} — ${selected.value}`,
    block_anchor: `${repo.value}:${selected.value}`,
    block_preview: `${selected.value}:${line}`,
    heading: selected.value,
    kind: draftKind.value,
    body,
    line_number: line,
    repo: repo.value,
    revision: head.value || 'WORKTREE',
    file_path: selected.value,
  })
  pendingLine.value = null
  draft.value = ''
  repoNotes.value = await notes.forRepository(repo.value)
}

async function resolve(id: number) {
  await notes.resolve(id)
  repoNotes.value = await notes.forRepository(repo.value)
}

function toggleTheme() {
  dark.value = !dark.value
  document.documentElement.classList.toggle('dark', dark.value)
}

/* Another tool can hand a reader straight to a file, optionally in edit mode:
 *   /?repo=root&path=docs/README.md&line=12&edit=1
 */
async function openFromQuery() {
  const query = new URLSearchParams(location.search)
  const wanted = query.get('repo')
  const path = query.get('path')
  if (wanted && repositories.value.some((entry) => entry.name === wanted)) repo.value = wanted
  if (query.get('edit') === '1') editing.value = true
  if (!path) return false

  mode.value = 'files'
  await loadTree()
  await openFile(path)

  /* Either an explicit line, or the text the other tool was looking at. */
  const match = query.get('match')
  const line = Number(query.get('line')) || (match && fileText.value
    ? lineOf(fileText.value, match)
    : 0)
  if (line > 0) {
    await nextTick()
    window.setTimeout(() => filePane.value?.revealLine(line), 600)
  }
  return true
}

onMounted(async () => {
  dark.value = window.matchMedia('(prefers-color-scheme: dark)').matches
  document.documentElement.classList.toggle('dark', dark.value)
  await loadRepositories()
  if (!(await openFromQuery())) await loadRepository()
})

watch(repo, loadRepository)
watch([base, head], loadChanges)
</script>

<template>
  <div class="min-h-screen">
    <header class="flex flex-wrap items-center gap-4 border-b border-rule bg-paper px-6 py-3">
      <span class="font-display text-lg font-extrabold tracking-tight text-ink">Bunko Review</span>

      <select
        v-model="repo"
        class="kicker border border-rule bg-surface px-2 py-1.5 text-ink"
        aria-label="Repository"
      >
        <option v-for="entry in repositories" :key="entry.name" :value="entry.name">
          {{ entry.name }}{{ entry.dirty ? ' •' : '' }}
        </option>
      </select>

      <div class="flex items-center gap-2">
        <GitBranch class="size-3.5 text-faint" />
        <select v-model="base" class="kicker border border-rule bg-surface px-2 py-1.5 text-ink" aria-label="Base">
          <option value="">working tree vs HEAD</option>
          <option v-for="branch in branches" :key="branch.name" :value="branch.name">{{ branch.name }}</option>
        </select>
        <span v-if="base" class="kicker">compared with</span>
        <select
          v-if="base"
          v-model="head"
          class="kicker border border-rule bg-surface px-2 py-1.5 text-ink"
          aria-label="Head"
        >
          <option value="">choose a branch</option>
          <option v-for="branch in branches" :key="branch.name" :value="branch.name">{{ branch.name }}</option>
        </select>
      </div>

      <div class="ml-auto flex items-center gap-2">
        <Button variant="ghost" size="sm" :disabled="loading" @click="loadRepository">
          <RefreshCw class="size-3.5" :class="loading && 'animate-spin'" />
          Refresh
        </Button>
        <Button
          :variant="mode === 'changes' ? 'default' : 'ghost'"
          size="sm"
          @click="switchMode('changes')"
        >
          <FileDiff class="size-3.5" />
          Changes
        </Button>
        <Button
          :variant="mode === 'files' ? 'default' : 'ghost'"
          size="sm"
          @click="switchMode('files')"
        >
          <FolderTree class="size-3.5" />
          Files
        </Button>
        <Button
          v-if="mode === 'files'"
          :variant="editing ? 'default' : 'ghost'"
          size="sm"
          :title="editing ? 'Editing: changes are tracked until committed' : 'Read only'"
          @click="editing = !editing"
        >
          <Pencil class="size-3.5" />
          {{ editing ? 'Editing' : 'Edit' }}
        </Button>
        <Button v-if="mode === 'changes'" variant="ghost" size="sm" @click="split = !split">
          <component :is="split ? Columns2 : Rows2" class="size-3.5" />
          {{ split ? 'Split' : 'Unified' }}
        </Button>
        <Button variant="ghost" size="icon-sm" aria-label="Toggle theme" @click="toggleTheme">
          <component :is="dark ? Sun : Moon" class="size-3.5" />
        </Button>
      </div>
    </header>

    <p v-if="problem" class="border-b border-rule bg-surface px-6 py-2 text-sm text-stop">{{ problem }}</p>

    <div class="grid gap-0 lg:grid-cols-[320px_minmax(0,1fr)]">
      <aside class="border-r border-rule bg-paper">
        <div class="flex items-baseline justify-between border-b border-rule px-4 py-3">
          <span class="kicker">{{ mode === 'files' ? 'All files' : 'Changed files' }}</span>
          <Badge variant="secondary" class="kicker">
            {{ mode === 'files' ? treePaths.length : files.length }}
          </Badge>
        </div>

        <p v-if="current" class="border-b border-rule px-4 py-2 font-mono text-[11px] text-faint">
          {{ comparing ? `${base} … ${head}` : `${current.head} · uncommitted` }}
        </p>

        <FileTreePane
          v-if="mode === 'files'"
          :paths="treePaths"
          :status="treeStatus"
          :selected="selected"
          @select="openFile"
        />

        <ul v-else class="max-h-[calc(100vh-9rem)] overflow-y-auto">
          <li v-for="file in files" :key="file.path">
            <button
              class="flex w-full items-baseline gap-2 border-b border-dotted border-rule px-4 py-2 text-left text-[13px] hover:bg-surface"
              :class="selected === file.path && 'border-l-[3px] border-l-accent bg-accent-tint'"
              @click="open(file.path)"
            >
              <span class="min-w-0 flex-1 truncate text-ink" :title="file.path">{{ file.path }}</span>
              <span v-if="countFor(file.path)" class="kicker text-accent">{{ countFor(file.path) }}</span>
              <span v-if="!file.binary" class="font-mono text-[11px] text-ok">+{{ file.added }}</span>
              <span v-if="!file.binary" class="font-mono text-[11px] text-stop">-{{ file.removed }}</span>
              <span v-else class="kicker">bin</span>
            </button>
          </li>
        </ul>

        <p v-if="mode === 'changes' && !files.length && !loading" class="px-4 py-6 text-sm text-faint">
          Nothing to review in this range.
        </p>
      </aside>

      <main class="min-w-0 p-6">
        <div v-if="dirtyPaths.length" class="mb-4 border border-ink bg-surface">
          <div class="flex items-baseline gap-3 border-b border-rule px-4 py-2">
            <GitCommitHorizontal class="size-3.5 text-accent" />
            <span class="kicker">{{ dirtyPaths.length }} file(s) changed, not committed</span>
            <Button variant="ghost" size="xs" class="ml-auto" @click="discardDrafts">Discard</Button>
          </div>
          <ul class="max-h-28 overflow-y-auto border-b border-rule">
            <li
              v-for="path in dirtyPaths"
              :key="path"
              class="cursor-pointer px-4 py-1.5 font-mono text-[12px] text-ink hover:bg-paper"
              @click="openFile(path)"
            >
              {{ path }}
            </li>
          </ul>
          <div class="flex items-center gap-2 p-3">
            <input
              v-model="commitMessage"
              placeholder="Commit message"
              class="min-w-0 flex-1 border border-rule bg-paper px-2 py-1.5 text-sm text-ink"
              @keydown.meta.enter="commitDrafts"
            />
            <Button size="sm" @click="saveWorkingTree">Save files</Button>
            <Button size="sm" :disabled="!commitMessage.trim()" @click="commitDrafts">Commit</Button>
          </div>
        </div>

        <p v-if="committed" class="mb-4 border border-rule bg-surface px-4 py-2 text-sm text-ok">
          {{ committed }}
        </p>

        <div v-if="selected">
          <div class="mb-3 flex items-baseline gap-3">
            <h1 class="font-mono text-sm text-ink">{{ selected }}</h1>
            <span class="kicker">click a line number to comment</span>
          </div>

          <ul v-if="fileNotes.length" class="mb-4 border border-rule bg-surface">
            <li
              v-for="note in fileNotes"
              :key="note.id"
              class="flex items-baseline gap-3 border-b border-dotted border-rule px-4 py-2 last:border-b-0"
            >
              <span class="kicker text-accent">{{ note.kind }}</span>
              <span v-if="note.line_number" class="font-mono text-[11px] text-faint">{{ note.page_path.startsWith('review:') ? `L${note.line_number}` : note.block_preview }}</span>
              <span class="min-w-0 flex-1 text-[13px] text-ink">{{ note.body }}</span>
              <Button variant="ghost" size="xs" @click="resolve(note.id)">Resolve</Button>
            </li>
          </ul>

          <div
            v-if="pendingLine !== null"
            class="mb-4 border border-ink bg-surface"
          >
            <div class="flex items-baseline gap-3 border-b border-rule px-4 py-2">
              <span class="kicker">Comment on line {{ pendingLine }}</span>
              <select v-model="draftKind" class="kicker ml-auto border border-rule bg-paper px-2 py-1 text-ink">
                <option v-for="kind in KINDS" :key="kind" :value="kind">{{ kind }}</option>
              </select>
            </div>
            <div class="p-4">
              <textarea
                v-model="draft"
                rows="3"
                autofocus
                placeholder="What should change here?"
                class="w-full border border-rule bg-paper p-2 text-sm text-ink"
                @keydown.esc="cancelComment"
                @keydown.meta.enter="saveComment"
              />
              <div class="mt-2 flex justify-end gap-2">
                <Button variant="ghost" size="sm" @click="cancelComment">Cancel</Button>
                <Button size="sm" :disabled="!draft.trim()" @click="saveComment">Save comment</Button>
              </div>
            </div>
          </div>

          <FilePane
            v-if="mode === 'files'"
            ref="filePane"
            :path="selected"
            :contents="fileText"
            :dark="dark"
            :notes="fileNotes"
            :editing="editing"
            @comment="startComment"
            @change="recordDraft"
          />

          <DiffPane
            v-else
            :path="selected"
            :old-text="oldText"
            :new-text="newText"
            :split="split"
            :dark="dark"
            :notes="fileNotes"
            @comment="startComment"
          />
        </div>

        <p v-else class="text-sm text-faint">Select a file to review.</p>
      </main>
    </div>
  </div>
</template>
