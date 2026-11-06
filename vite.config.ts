import { defineConfig } from 'vite';
const pages = ['index', 'toy', 'app', 'lab', 'bounties', 'home', 'crashlab', 'simulation', 'screener', 'data', 'providers', 'login'];
// scripts/demo.sh sets the site server's port when 5297 is taken.
const site = `http://127.0.0.1:${process.env.CRASHLAB_SITE_PORT ?? 5297}`;
export default defineConfig({
  optimizeDeps: { exclude: ['@mujoco/mujoco'] },
  // In a demo a saved file must not reload the judge's page, so scripts/demo.sh turns live reload off.
  // The repo holds large run and design folders. Watching them kept vite above 150% CPU.
  server: { port: 5199, watch: { ignored: ['**/policy/**', '**/design/**', '**/status/**', '**/contracts/**', '**/docs/**', '**/.claude/**', '**/public/generated/**', '**/public/trials/**'] }, ...(process.env.CRASHLAB_DEMO ? { hmr: false, watch: null } : {}), proxy: { '/site-api': site, '^/trials/demo-window-': site } },
  build: { target: 'es2022', rollupOptions: { input: Object.fromEntries(pages.map(p => [p === 'index' ? 'main' : p, `${p}.html`])) } },
});
