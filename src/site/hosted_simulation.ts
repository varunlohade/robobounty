// The Simulation page on the hosted site. The simulator needs this repo on a Mac, so the page says so and shows nothing else.
import { mountShell } from './shell.ts';
import { h } from './ui.ts';

const REPO_URL = ''; // While empty, the link stays hidden. The repo is private for now.

const { main } = mountShell({ page: 'simulation', title: 'Simulation' });
main.append(h('p', 'quiet', 'Simulation runs on your Mac. Download the GitHub repo to run it.'));
if (REPO_URL) main.append(Object.assign(h('a', 'btn sec', 'Open the GitHub repo'), { href: REPO_URL, target: '_blank', rel: 'noopener' }));
