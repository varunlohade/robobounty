// One command for the whole paid flow: start the API, run the agent, stop the API.
// Arguments go to the agent, for example: node policy/x402/run.mjs --budget 0.07
import { spawn } from "node:child_process";
import { join } from "node:path";
import { HERE, PORT } from "./lib.mjs";

const server = spawn(process.execPath, [join(HERE, "server.mjs")], { stdio: ["ignore", "ignore", "inherit"] });
const stop = (code) => { server.kill(); process.exit(code); };

let up = false;
for (let i = 0; i < 60 && !up; i++) {
  await new Promise((r) => setTimeout(r, 500));
  up = await fetch(`http://127.0.0.1:${PORT}/.well-known/x402`).then((r) => r.ok, () => false);
}
if (!up) { console.error("server did not start"); stop(1); }

spawn(process.execPath, [join(HERE, "agent.mjs"), ...process.argv.slice(2)], { stdio: "inherit" }).on("exit", (code) => stop(code ?? 1));
