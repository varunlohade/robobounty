import { defineConfig } from 'vite';
export default defineConfig({
  optimizeDeps: { exclude: ['@mujoco/mujoco'] },
  server: { port: 5199 },
  build: { target: 'es2022', rollupOptions: { input: { main: 'index.html', app: 'app.html' } } },
});
