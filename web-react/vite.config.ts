import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

const apiTarget = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react(), VitePWA({
    strategies: 'injectManifest',
    srcDir: 'src/pwa',
    filename: 'sw.js',
    injectRegister: false,
    manifest: false,
    injectManifest: {
      globPatterns: ['**/*.{js,css,html,png,svg,webmanifest}'],
      globIgnores: ['**/._*'],
      maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
    },
  })],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: false },
      '/files': { target: apiTarget, changeOrigin: false },
      '/generated': { target: apiTarget, changeOrigin: false },
    },
  },
});
