import { resolve } from 'node:path';
export default {
  root: import.meta.dirname,
  build: { outDir: 'out/dist', target: 'esnext', rollupOptions: { input: resolve(import.meta.dirname, 'viewer.html') } },
  optimizeDeps: { exclude: ['@rerun-io/web-viewer'] },
  server: { host: '127.0.0.1', port: 5333, strictPort: true, fs: { allow: [import.meta.dirname] } },
};
