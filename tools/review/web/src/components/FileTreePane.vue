<script setup lang="ts">
import { onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { FileTree, type GitStatusEntry } from '@pierre/trees'

const props = defineProps<{
  paths: string[]
  status: GitStatusEntry[]
  selected: string
}>()

const emit = defineEmits<{ select: [path: string] }>()

const host = ref<HTMLElement>()
const instance = shallowRef<FileTree | undefined>()

function build() {
  if (!host.value || !props.paths.length) return
  instance.value?.cleanUp()

  instance.value = new FileTree({
    paths: props.paths,
    gitStatus: props.status,
    search: true,
    // A repository opens closed; expanding everything is unusable at this size.
    initialExpansion: 'closed',
    initialSelectedPaths: props.selected ? [props.selected] : [],
    onSelectionChange: (paths: readonly string[]) => {
      const path = paths[0]
      // Directories are selectable too; only files have contents to show.
      if (path && props.paths.includes(path)) emit('select', path)
    },
  })

  instance.value.render({ containerWrapper: host.value })
}

watch(() => [props.paths, props.status], build, { deep: true })
watch(host, build, { immediate: true })
onBeforeUnmount(() => instance.value?.cleanUp())
</script>

<template>
  <div ref="host" class="h-[calc(100vh-9rem)] overflow-hidden" />
</template>
