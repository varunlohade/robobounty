import { defineConfig } from 'vite';
const pages = ['index', 'toy', 'app', 'lab', 'bounties', 'home', 'crashlab', 'data', 'providers', 'login'];
// scripts/demo.sh sets the site server's port when 5297 is taken.
const site = `http://127.0.0.1:${process.env.CRASHLAB_SITE_PORT ?? 5297}`;
export default defineConfig({
  optimizeDeps: { exclude: ['@mujoco/mujoco'] },
  server: { port: 5199, proxy: { '/site-api': site, '^/trials/demo-window-': site } },
  build: { target: 'es2022', rollupOptions: { input: Object.fromEntries(pages.map(p => [p === 'index' ? 'main' : p, `${p}.html`])) } },
});
