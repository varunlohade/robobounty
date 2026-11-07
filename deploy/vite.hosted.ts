// The Vercel build. Pages only, with the hosted Simulation page in place of the simulator. Local builds use vite.config.ts and never read this file.
import { resolve } from 'node:path';
import { defineConfig } from 'vite';

const pages = ['home', 'failures', 'bounties', 'data', 'settings', 'providers', 'screener', 'login', 'simulation'];
const root = resolve(import.meta.dirname, '..');
export default defineConfig({
  root,
  resolve: { alias: [{ find: '/src/site/simulation.ts', replacement: resolve(root, 'src/site/hosted_simulation.ts') }] },
  build: { target: 'es2022', rollupOptions: { input: Object.fromEntries(pages.map(p => [p, resolve(root, `${p}.html`)])) } },
});
