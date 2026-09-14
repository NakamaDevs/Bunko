<script setup lang="ts">
import { onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { File, preloadHighlighter } from '@pierre/diffs'
import { Editor } from '@pierre/diffs/edit'
import type { Note } from '@/lib/api'

const props = defineProps<{
  path: string
  contents: string | null
  dark: boolean
  notes: Note[]
  editing: boolean
}>()

const emit = defineEmits<{ comment: [line: number]; change: [contents: string] }>()

/* Scroll a line into view. The component renders rows in a shadow root, so the
 * row is found there rather than through the document. */
function revealLine(line: number) {
  const container = host.value?.querySelector('diffs-container')
  const root = (container as HTMLElement & { shadowRoot?: ShadowRoot })?.shadowRoot
  const row = root?.querySelector(`[data-line-index="${line - 1}"]`)
  if (!row) return false
  row.scrollIntoView({ behavior: 'smooth', block: 'center' })
  return true
}

defineExpose({ revealLine })

const host = ref<HTMLElement>()
const instance = shallowRef<File<Note> | undefined>()
const editor = shallowRef<Editor<'file', Note> | undefined>()
const detach = shallowRef<(() => void) | undefined>()
const failure = ref('')

/* The editor is attached to the rendered file rather than replacing it, so a
 * file reads the same whether or not it is being edited. */
function attachEditor() {
  if (!props.editing || !instance.value || detach.value) return
  editor.value = new Editor('file', {
    onChange: () => emit('change', editor.value?.getFile()?.contents ?? ''),
  })
  detach.value = editor.value.edit(instance.value)
}

function detachEditor() {
  detach.value?.()
  detach.value = undefined
  editor.value = undefined
}

function annotations() {
  return props.notes
    .filter((note) => note.page_path.startsWith('review:') && note.line_number && note.file_path === props.path)
    .map((note) => ({ lineNumber: note.line_number as number, metadata: note }))
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
    overflow: 'wrap' as const,
    renderAnnotation: (annotation: { metadata?: Note }) =>
      annotation.metadata ? annotationElement(annotation.metadata) : undefined,
    onLineNumberClick: (event: { lineNumber: number }) => emit('comment', event.lineNumber),
  }
}

async function draw() {
  failure.value = ''
  if (!host.value || props.contents === null) return
  try {
    await preloadHighlighter({ themes: ['pierre-light', 'pierre-dark'], langs: [] })
    /* A rerender replaces the rendered rows, so an attached editor is released
     * first and reattached against the new ones. */
    const wasEditing = Boolean(detach.value)
    if (wasEditing) detachEditor()

    if (!instance.value) instance.value = new File<Note>(options())
    else instance.value.setOptions(options())

    instance.value.render({
      file: { name: props.path, contents: props.contents },
      containerWrapper: host.value,
      lineAnnotations: annotations(),
      forceRender: true,
    })
    if (props.editing) attachEditor()
  } catch (error) {
    failure.value = error instanceof Error ? error.message : String(error)
  }
}

watch(() => [props.path, props.contents, props.dark], draw, { immediate: true, deep: true })
watch(() => props.notes, () => instance.value?.setLineAnnotations(annotations()), { deep: true })
watch(host, draw)
watch(() => props.editing, (on) => (on ? attachEditor() : detachEditor()))
watch(instance, () => { if (props.editing) attachEditor() })
onBeforeUnmount(() => {
  detachEditor()
  instance.value?.cleanUp()
})
</script>

<template>
  <div>
    <p v-if="failure" class="border border-rule bg-surface p-4 text-sm text-stop">{{ failure }}</p>
    <div ref="host" class="border border-rule bg-surface" />
  </div>
</template>
