<script setup lang="ts">
import { onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { FileDiff, preloadHighlighter } from '@pierre/diffs'
import type { Note } from '@/lib/api'

const props = defineProps<{
  path: string
  oldText: string | null
  newText: string | null
  split: boolean
  dark: boolean
  notes: Note[]
}>()

const emit = defineEmits<{ comment: [line: number] }>()

const host = ref<HTMLElement>()
const instance = shallowRef<FileDiff<Note> | undefined>()
const failure = ref('')

/** Comments sit on the additions side, which is the side under review. */
function annotations() {
  return props.notes
    .filter((note) => note.page_path.startsWith('review:') && note.line_number && note.file_path === props.path)
    .map((note) => ({
      side: 'additions' as const,
      lineNumber: note.line_number as number,
      metadata: note,
    }))
}

function annotationElement(note: Note) {
  const row = document.createElement('div')
  row.className =
    'flex items-baseline gap-2 border-l-[3px] border-accent bg-accent-tint px-3 py-1.5 text-[13px] leading-snug'
  const kind = document.createElement('span')
  kind.className = 'kicker text-accent'
  kind.textContent = note.kind
  const body = document.createElement('span')
  body.className = 'text-ink'
  body.textContent = note.body
  row.append(kind, body)
  return row
}

function options() {
  return {
    theme: props.dark ? 'pierre-dark' : 'pierre-light',
    diffStyle: props.split ? ('split' as const) : ('unified' as const),
    overflow: 'wrap' as const,
    renderAnnotation: (annotation: { metadata?: Note }) =>
      annotation.metadata ? annotationElement(annotation.metadata) : undefined,
    onLineNumberClick: (event: { lineNumber: number }) => emit('comment', event.lineNumber),
  }
}

async function draw() {
  failure.value = ''
  if (!host.value) return
  if (props.oldText === null && props.newText === null) return

  try {
    await preloadHighlighter({ themes: ['pierre-light', 'pierre-dark'], langs: [] })

    if (!instance.value) instance.value = new FileDiff<Note>(options())
    else instance.value.setOptions(options())

    /* A null side means the file was added or deleted in this range. */
    instance.value.render({
      oldFile: props.oldText === null ? null : { name: props.path, contents: props.oldText },
      newFile: props.newText === null ? null : { name: props.path, contents: props.newText },
      containerWrapper: host.value,
      lineAnnotations: annotations(),
      forceRender: true,
    } as never)
  } catch (error) {
    failure.value = error instanceof Error ? error.message : String(error)
  }
}

watch(
  () => [props.path, props.oldText, props.newText, props.split, props.dark],
  draw,
  { immediate: true, deep: true },
)

/* Adding or resolving a comment only changes the annotations. */
watch(
  () => props.notes,
  () => instance.value?.setLineAnnotations(annotations()),
  { deep: true },
)
watch(host, draw)
onBeforeUnmount(() => instance.value?.cleanUp())
</script>

<template>
  <div>
    <p v-if="failure" class="border border-rule bg-surface p-4 text-sm text-stop">
      {{ failure }}
    </p>
    <div ref="host" class="border border-rule bg-surface" />
  </div>
</template>
