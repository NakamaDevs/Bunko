import fs from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import tidewave from 'tidewave/vite-plugin'

const domain = process.env.BUNKO_DOMAIN || 'bunko.localhost'
const gatewayPort = process.env.BUNKO_PORT || '8870'

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
