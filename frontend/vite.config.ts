import { readFileSync } from 'node:fs'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, loadEnv } from 'vite'

/**
 * Dev proxy: with VITE_API_URL=/api the browser only talks to this dev server, which forwards
 * /api/* to the StreamSense API. Server-side settings (no VITE_ prefix, never sent to the browser):
 *   STREAMSENSE_API_TARGET         e.g. http://atl1-1-03-020-34-0.pace.gatech.edu:43211
 *   STREAMSENSE_API_ENDPOINT_FILE  or a file holding host:port (written by serve_gpu.sbatch)
 *   STREAMSENSE_API_TOKEN          shared token; added as Authorization on every proxied request
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  let target = env.STREAMSENSE_API_TARGET
  if (!target && env.STREAMSENSE_API_ENDPOINT_FILE) {
    try {
      target = `http://${readFileSync(env.STREAMSENSE_API_ENDPOINT_FILE, 'utf8').trim()}`
    } catch {
      console.warn(`[streamsense] endpoint file not readable: ${env.STREAMSENSE_API_ENDPOINT_FILE}`)
    }
  }
  const token = env.STREAMSENSE_API_TOKEN
  if (target) console.log(`[streamsense] proxy /api -> ${target}${token ? ' (token set)' : ''}`)
  const proxy = target
    ? {
        '/api': {
          target,
          changeOrigin: true,
          rewrite: (p: string) => p.replace(/^\/api/, ''),
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        },
      }
    : undefined
  // `vite preview` serves the production build (3 files) with the same proxy: much faster than
  // the dev server's per-module requests over a high-latency port-forward.
  return { plugins: [react(), tailwindcss()], server: { proxy }, preview: { proxy } }
})
