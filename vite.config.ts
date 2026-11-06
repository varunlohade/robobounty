import { defineConfig } from 'vite';
const pages = ['index', 'toy', 'app', 'lab', 'bounties', 'home', 'crashlab', 'data', 'providers', 'login'];
export default defineConfig({
  optimizeDeps: { exclude: ['@mujoco/mujoco'] },
  server: { port: 5199, proxy: { '/site-api': 'http://127.0.0.1:5297', '^/trials/demo-window-': 'http://127.0.0.1:5297' } },
  build: { target: 'es2022', rollupOptions: { input: Object.fromEntries(pages.map(p => [p === 'index' ? 'main' : p, `${p}.html`])) } },
});
