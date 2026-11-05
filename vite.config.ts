import { defineConfig } from 'vite';
export default defineConfig({
  optimizeDeps: { exclude: ['@mujoco/mujoco'] },
  server: { port: 5199 },
});
