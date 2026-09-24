import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { parse, compileScript } from '@vue/compiler-sfc'
import { build } from 'esbuild'

// Exercise the actual SFC setup and API, without DOM-only rendering dependencies.
const root = fileURLToPath(new URL('../', import.meta.url))
const { descriptor } = parse(await readFile(root + 'src/App.vue', 'utf8'))
const compiled = compileScript(descriptor, { id: 'review-test' }).content
const result = await build({
  stdin: { contents: compiled, loader: 'ts', resolveDir: root },
  bundle: true, format: 'esm', platform: 'node', write: false,
  define: { 'import.meta.env': '{}' },
  alias: { '@': root + 'src' },
  plugins: [{ name: 'render-stubs', setup(build) {
    build.onResolve({ filter: /^(vue)$/ }, () => ({ path: import.meta.resolve('vue'), external: true }))
    build.onResolve({ filter: /(\.vue$|components\/ui\/|lucide-vue-next)/ }, args => ({ path: args.path, namespace: 'stub' }))
    build.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({ contents: 'export default {}; export const Button={},Badge={},GitBranch={},RefreshCw={},Columns2={},Rows2={},Moon={},Sun={},FileDiff={},FolderTree={},Pencil={},GitCommitHorizontal={},GitFork={};' }))
  } }],
})
globalThis.location = { origin: 'http://review.localhost:8870' }
const { default: component } = await import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64'))
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
function app() {
  globalThis.fetch = async url => {
    if (String(url).includes('/blob')) return json({ contents: 'checkout contents' })
    return json({ branches: [], notes: [], files: [], paths: [], status: [] })
  }
  return component.setup({}, { expose() {} })
}

test('drafts are isolated by repository; revision blobs cannot become working-tree drafts', async () => {
  const a = app()
  a.repo.value = 'A'; a.mode.value = 'files'
  await a.openFile('foo.md'); a.editing.value = true; a.recordDraft('A draft')
  a.repo.value = 'B'; await a.openFile('foo.md')
  assert.equal(a.fileText.value, 'checkout contents')
  assert.equal(a.dirtyPaths.value.length, 0)
  a.repo.value = 'A'; await a.openFile('foo.md')
  assert.equal(a.fileText.value, 'A draft')
  a.base.value = 'main'; a.head.value = 'other'; await a.openFile('foo.md')
  assert.equal(a.fileText.value, 'checkout contents')
  assert.equal(a.canEdit.value, false)
  a.editing.value = true; a.recordDraft('stale branch')
  assert.equal(a.drafts.value.get('foo.md'), 'A draft')
})

test('a save in flight remains bound to the original repository', async () => {
  const a = app(); a.repo.value = 'A'; a.mode.value = 'files'
  for (const path of ['one.md', 'two.md']) {
    await a.openFile(path); a.editing.value = true; a.recordDraft('A draft')
  }
  const writes = []
  let release
  globalThis.fetch = async (url, options) => {
    if (!options?.method) return json({ branches: [], notes: [], files: [] })
    writes.push(String(url))
    if (writes.length === 1) await new Promise(resolve => { release = resolve })
    return json({ path: 'saved' })
  }
  const save = a.saveWorkingTree()
  a.repo.value = 'B'; release(); await save
  assert.equal(writes.length, 2)
  assert.ok(writes.every(url => url.includes('/repos/A/file')))
})

test('failed note writes retain the draft and report the error', async () => {
  const a = app(); a.pendingLine.value = 3; a.draft.value = 'Keep this comment'
  globalThis.fetch = async () => json({ error: 'Disk full' }, 500)
  await a.saveComment()
  assert.equal(a.draft.value, 'Keep this comment')
  assert.equal(a.pendingLine.value, 3)
  assert.equal(a.problem.value, 'Disk full')
  globalThis.fetch = async () => json({ notes: [] })
  await a.saveComment()
  assert.equal(a.draft.value, '')
  assert.equal(a.pendingLine.value, null)
})


test('diff sides ignore out-of-order responses and changed review context', async () => {
  const a = app(); a.repo.value = 'A'
  const pending = []
  globalThis.fetch = url => String(url).includes('/sides')
    ? new Promise(resolve => pending.push(resolve))
    : Promise.resolve(json({ branches: [], notes: [], files: [], paths: [], status: [] }))
  const first = a.open('one.md')
  const second = a.open('two.md')
  pending[1](json({ old: 'two old', new: 'two new' })); await second
  pending[0](json({ old: 'one old', new: 'one new' })); await first
  assert.equal(a.selected.value, 'two.md')
  assert.equal(a.newText.value, 'two new')
  for (const field of ['repo', 'base', 'head', 'mode']) {
    const request = a.open('two.md')
    assert.equal(a.newText.value, null)
    a[field].value = 'changed-' + field
    pending.at(-1)(json({ old: 'stale', new: 'stale' })); await request
    assert.equal(a.newText.value, null)
  }
})
