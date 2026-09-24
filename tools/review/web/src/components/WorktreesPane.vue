<script setup lang="ts">
import { computed, ref } from 'vue'
import { Copy, Check } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import type { Worktree, WorktreeState } from '@/lib/api'

const props = defineProps<{ worktrees: Worktree[]; loading: boolean }>()
const emit = defineEmits<{ open: [id: string] }>()

/* A reader decides one of three things about a worktree: remove it, look at it,
 * or leave it alone. The filters follow those decisions, not the raw states. */
type Filter = 'all' | 'prune' | 'check' | 'working'
const FILTERS: { key: Filter; label: string; title: string }[] = [
  { key: 'all', label: 'All', title: 'Every linked worktree' },
  { key: 'prune', label: 'Can prune', title: 'Missing, merged or squash-merged, with no uncommitted changes' },
  { key: 'check', label: 'Check', title: 'The remote branch was deleted, but some commits are not on an integration branch' },
  { key: 'working', label: 'In progress', title: 'Uncommitted changes, or commits not merged yet' },
]

const STATES: Record<WorktreeState, { label: string; tone: string }> = {
  missing: { label: 'Missing', tone: 'text-stop' },
  merged: { label: 'Merged', tone: 'text-ok' },
  integrated: { label: 'Squash-merged', tone: 'text-ok' },
  gone: { label: 'Remote deleted', tone: 'text-accent' },
  dirty: { label: 'Uncommitted', tone: 'text-accent' },
  active: { label: 'Active', tone: 'text-ink' },
}

const filter = ref<Filter>('all')
const search = ref('')
const copied = ref('')

function matches(entry: Worktree, key: Filter) {
  if (key === 'prune') return entry.can_prune
  if (key === 'check') return entry.state === 'gone'
  if (key === 'working') return entry.state === 'dirty' || entry.state === 'active'
  return true
}

const counts = computed(() =>
  Object.fromEntries(FILTERS.map(({ key }) => [key, props.worktrees.filter((entry) => matches(entry, key)).length])),
)

const visible = computed(() => {
  const needle = search.value.trim().toLowerCase()
  return props.worktrees.filter((entry) => matches(entry, filter.value)
    && (!needle || [entry.id, entry.branch ?? '', entry.path, entry.last_commit_subject ?? '']
      .some((value) => value.toLowerCase().includes(needle))))
})

const groups = computed(() => {
  const byRepository = new Map<string, Worktree[]>()
  for (const entry of visible.value) {
    byRepository.set(entry.repository, [...(byRepository.get(entry.repository) ?? []), entry])
  }
  return [...byRepository.entries()]
})

const prunable = computed(() => visible.value.filter((entry) => entry.cleanup.length))
const visibleCleanup = computed(() => prunable.value.flatMap((entry) => entry.cleanup))

function age(seconds: number | null) {
  if (!seconds) return ''
  const days = Math.floor((Date.now() / 1000 - seconds) / 86400)
  if (days < 1) return 'today'
  if (days < 30) return `${days}d ago`
  if (days < 365) return `${Math.floor(days / 30)}mo ago`
  return `${Math.floor(days / 365)}y ago`
}

async function copy(key: string, commands: string[]) {
  await navigator.clipboard.writeText(commands.join('\n') + '\n')
  copied.value = key
  window.setTimeout(() => { if (copied.value === key) copied.value = '' }, 1500)
}
</script>

<template>
  <section class="p-6">
    <div class="mb-4 flex flex-wrap items-center gap-2">
      <Button
        v-for="option in FILTERS"
        :key="option.key"
        :variant="filter === option.key ? 'default' : 'ghost'"
        size="sm"
        :title="option.title"
        @click="filter = option.key"
      >
        {{ option.label }}
        <span class="font-mono text-[11px] opacity-80">{{ counts[option.key] }}</span>
      </Button>
      <input
        v-model="search"
        placeholder="Filter by name, branch or path"
        aria-label="Filter worktrees"
        class="ml-2 min-w-56 flex-1 border border-rule bg-surface px-2 py-1.5 text-sm text-ink"
      />
      <Button
        variant="ghost"
        size="sm"
        :disabled="!visibleCleanup.length"
        title="Copy the cleanup commands of every worktree shown that can be pruned"
        @click="copy('all', visibleCleanup)"
      >
        <component :is="copied === 'all' ? Check : Copy" class="size-3.5" />
        Copy cleanup for {{ prunable.length }}
      </Button>
    </div>

    <p class="mb-4 text-[13px] text-faint">
      Merged means every commit is on an integration branch (<code>origin/HEAD</code>, <code>main</code>,
      <code>master</code>, <code>dev</code> or <code>develop</code>) as of the last fetch. Fetch first for
      a current answer. Bunko never removes a worktree: copy the commands and run them yourself.
    </p>

    <p v-if="loading && !worktrees.length" class="text-sm text-faint">Reading worktrees…</p>
    <p v-else-if="!visible.length" class="text-sm text-faint">No worktrees match.</p>

    <div v-for="[name, entries] in groups" :key="name" class="mb-6 border border-rule bg-surface">
      <div class="flex items-baseline gap-3 border-b border-rule px-4 py-2">
        <span class="kicker text-ink">{{ name }}</span>
        <span class="kicker">{{ entries.length }} worktree(s)</span>
      </div>
      <table class="w-full table-fixed text-left text-[13px]">
        <colgroup>
          <col class="w-[34%]" />
          <col class="w-[30%]" />
          <col />
          <col class="w-44" />
        </colgroup>
        <thead>
          <tr class="border-b border-rule">
            <th class="kicker px-4 py-2 font-normal">Worktree</th>
            <th class="kicker px-4 py-2 font-normal">State</th>
            <th class="kicker px-4 py-2 font-normal">Last commit</th>
            <th class="px-4 py-2" />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="entry in entries"
            :key="entry.id"
            class="border-b border-dotted border-rule align-top last:border-b-0"
          >
            <td class="px-4 py-2">
              <div class="truncate text-ink" :title="entry.slug">{{ entry.slug }}</div>
              <div class="truncate font-mono text-[11px] text-faint" :title="entry.branch ?? 'detached HEAD'">
                {{ entry.branch ?? `detached at ${entry.head.slice(0, 7)}` }}
              </div>
              <div class="truncate font-mono text-[11px] text-faint" :title="entry.path">{{ entry.path }}</div>
            </td>
            <td class="px-4 py-2">
              <span class="kicker" :class="STATES[entry.state].tone">{{ STATES[entry.state].label }}</span>
              <span v-if="entry.locked" class="kicker ml-2" title="git worktree lock">Locked</span>
              <div class="text-[12px] text-body">{{ entry.reason }}</div>
              <div v-if="entry.behind" class="font-mono text-[11px] text-faint">
                {{ entry.behind }} behind {{ entry.default_ref }}
              </div>
            </td>
            <td class="px-4 py-2">
              <div class="font-mono text-[11px] text-faint">{{ age(entry.last_commit_at) }}</div>
              <div class="truncate text-[12px] text-body" :title="entry.last_commit_subject ?? ''">
                {{ entry.last_commit_subject }}
              </div>
            </td>
            <td class="whitespace-nowrap px-4 py-2 text-right">
              <Button v-if="entry.exists" variant="ghost" size="xs" @click="emit('open', entry.id)">Review</Button>
              <Button
                v-if="entry.cleanup.length"
                variant="ghost"
                size="xs"
                :title="entry.cleanup.join('\n')"
                @click="copy(entry.id, entry.cleanup)"
              >
                <component :is="copied === entry.id ? Check : Copy" class="size-3" />
                Cleanup
              </Button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
