import fs from 'node:fs'
import { dirname, resolve, sep } from 'node:path'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import tidewave from 'tidewave/vite-plugin'

const domain = process.env.BUNKO_DOMAIN || 'bunko.localhost'
const gatewayPort = process.env.BUNKO_PORT || '8870'
const THEME_ROUTE = '/bunko-theme/'

// The consumer's reviewer title and stylesheets, mirroring review/appearance.py.
function appearance() {
  const config = process.env.BUNKO_CONFIG
  if (!config || !fs.existsSync(config)) return { title: undefined, sheets: [] as string[] }
  const root = dirname(resolve(config))
  const review = JSON.parse(fs.readFileSync(config, 'utf-8')).review ?? {}
  const sheets = (review.stylesheets ?? []).map((item: string) => resolve(root, item))
    .filter((sheet: string) => sheet.startsWith(root + sep) && sheet.endsWith('.css'))
  return { title: review.title as string | undefined, sheets }
}

const bunkoAppearance = (): Plugin => ({
  name: 'bunko-appearance',
  transformIndexHtml(html) {
    const { title, sheets } = appearance()
    const escaped = title?.replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`)
    const titled = escaped ? html.replace(/<title>.*?<\/title>/, `<title>${escaped}</title>`) : html
    const links = sheets.map((_: string, index: number) => `<link rel="stylesheet" href="${THEME_ROUTE}${index}.css" />`).join('')
    return titled.replace('</head>', `${links}</head>`)
  },
  configureServer(server) {
    server.middlewares.use((request, response, next) => {
      const match = request.url?.match(/^\/bunko-theme\/(\d+)\.css$/)
      const sheet = match && appearance().sheets[Number(match[1])]
      if (!sheet || !fs.existsSync(sheet)) return next()
      response.setHeader('Content-Type', 'text/css')
      response.end(fs.readFileSync(sheet))
    })
  },
})

// Aspire assigns the port and reaches the app through the gateway, so the dev
// server must accept the gateway hostname as well as localhost.
export default defineConfig({
  plugins: [
    // shadcn-vue components take prop types from reka-ui, so the SFC compiler
    // needs file access to resolve types across package boundaries.
    vue({
      script: {
        fs: {
          fileExists: (file: string) => fs.existsSync(file),
          readFile: (file: string) => fs.readFileSync(file, 'utf-8'),
        },
      },
    }),
    tailwindcss(),
    bunkoAppearance(),
    // Tidewave serves /tidewave in dev only. The gateway forwards that path
    // from both hosts, so the docs pages can load the same toolbar.
    tidewave({
      allowedOrigins: [
        '//127.0.0.1',
        '//localhost',
        `//docs.${domain}:${gatewayPort}`,
        `//review.${domain}:${gatewayPort}`,
      ],
      tmpDir: resolve(process.env.BUNKO_STATE || '../../../_build/bunko', 'tidewave'),
    }),
  ],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    host: '127.0.0.1',
    port: Number(process.env.PORT) || 5180,
    strictPort: true,
    allowedHosts: ['localhost', '127.0.0.1'],
  },
})
