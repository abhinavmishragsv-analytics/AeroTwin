import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    // maplibre-gl ships its own Web Worker bundle (maplibre-gl-worker.mjs).
    // Vite's dependency pre-bundler doesn't handle that worker file
    // correctly - it produces a benign-looking but confusing
    // "file does not exist ... in the optimize deps directory" warning on
    // dev-server startup, and can occasionally require an extra page
    // refresh on first load. Excluding maplibre-gl from pre-bundling lets
    // it load as native ESM instead, which resolves its own worker file
    // correctly.
    exclude: ['maplibre-gl'],
  },
})
