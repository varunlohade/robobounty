# Third-party models, tools and assets

"Source" says where each license entry comes from. "unknown" means this repo does not note a license and we did not read one upstream. Check every entry before any sale.

The repo itself has no license file yet.

## In the CrashLab flow

| Item | Version | License | Source | Use |
|---|---|---|---|---|
| MuJoCo (Python) | 3.8.1 | Apache-2.0 | package metadata, `policy/.venv` | Window robot physics |
| `@mujoco/mujoco` (WASM) | 3.16.0 | Apache-2.0 | `node_modules` package.json | Browser replay. It sets recorded states and never steps physics |
| Newton | 1.7.0 | Apache-2.0 | package metadata, `policy/.venv-newton` | Inspection robot physics, CPU |
| Warp (`warp-lang`) | 1.19.0 | Apache-2.0 | same | Newton's compute layer |
| `warp-nn` | 0.4.1 | Apache-2.0 | same | Runs the upstream walking policy |
| `mujoco-warp`, MuJoCo in the Newton env | 3.15.0 | Apache-2.0 | same | Newton's solver |
| ONNX | 1.23.2 | Apache-2.0 | same | Policy file format |
| ANYmal C robot model | from Newton's asset repo | BSD-3-Clause (ANYbotics) | `public/robots/anymal_c/LICENSE` | The inspection robot's body |
| Upstream walking policy `rl_policies/mjw_anymal.onnx` | from Newton's asset repo | unknown | `policy/packs/inspection/model.py` names the file, with no license note | Turns a speed command into 12 joint targets |
| three.js | 0.180.0 | MIT | package.json | Browser 3D |
| CodeMirror 6 (`state`, `view`, `commands`, `language`, `lang-json`, `lang-python`), `@lezer/highlight` | see `package.json` | MIT | package.json | Code tab |
| `@worldcoin/idkit-core` | 4.6.0 | MIT | package.json | World ID sign-in |
| `qrcode-generator` | 2.0.4 | MIT | package.json | Sign-in QR code |
| Vite, esbuild | 7.1.12, 0.25.12 | MIT | package.json | Dev server, build |
| TypeScript | 5.9.3 | Apache-2.0 | package.json | Language |
| NumPy | 2.2.6 | BSD | package metadata | Python numbers |
| Pillow | 12.3.0 | MIT-CMU | package metadata | Images |
| Rerun web viewer, `rerun-sdk` | 0.42.0 | MIT; MIT OR Apache-2.0 | package metadata | Optional "Open in Rerun" export |
| Inter, JetBrains Mono (font files) | | unknown | `src/lab/fonts`, no license file beside them | Interface text |
| Lucide icons | 0.400 | unknown | `AI-USE.md` names the version only | Board icons |

## AI services

| Item | License or terms | Use |
|---|---|---|
| Claude Code, model Claude Opus 5.5 (`claude-opus-5-5`) | Anthropic's terms; not read for this file | Wrote most code and docs. Headless calls in the lab's test loop |
| GPT through Codex, `gpt-6-astra` | OpenAI's terms; not read for this file | Design explorations, film treatment, concept stills, some scene files in an eval |

## Generated models

| Item | License | Source | Use |
|---|---|---|---|
| Qwen-Image-2512 | Apache-2.0 | noted in `AI-USE.md` | Reference pictures for `public/generated/` |
| Hunyuan3D-2.1 (`tencent/Hunyuan3D-2.1`) | Tencent Hunyuan non-commercial community license. It limits commercial use and some territories | noted in `AI-USE.md` and `policy/simfoundry_lab/GPU.md` | Textured meshes in `public/generated/` and `design/generated/` |
| RealESRGAN x4plus checkpoint | unknown | `policy/crashlab/gpu_service/hy_worker.py` loads it | Part of Hunyuan's paint step |
| Background removal model under `U2NET_HOME` | unknown | `policy/crashlab/gpu_service/service.py` sets the path | Part of the GPU service |
| CoACD | 1.0.14, MIT | package metadata, `policy/.venv-gen` | Convex hulls for generated objects |
| trimesh | 5.2.0, MIT | package metadata | Mesh checks |

Hunyuan3D's license is the main limit on any future sale. The five models in `public/generated/` and the one in `design/generated/` come from it.

<!-- CONFIRM: steve, the commercial limit on Hunyuan3D matters for the "paid app" plan, not for this hackathon entry. -->

## Render tools and assets

| Item | License | Source | Use |
|---|---|---|---|
| Blender (Cycles) | GPL | `README.md` | Renders of recorded runs. Not bundled |
| "Overcast Soil (Pure Sky)" by Sergej Majboroda, sky edits by Jarod Guest (Poly Haven) | CC0 | `AI-USE.md`. The live view's copy is `public/assets/sky/overcast_soil_top.jpg` | Sky |
| "Kloofendal Overcast (Pure Sky)" by Greg Zaal (Poly Haven) | CC0 | `policy/render/assets.py` | Sky in renders. Fetched at render time |
| ambientCG surface maps listed in `policy/render/assets.py` and any others in `design/render/_cache/tex` | CC0 | `policy/render/assets.py` states CC0 for its list | Surface detail in renders. Not in git |
| FFmpeg | unknown | used by `policy/render/hull.py`, not bundled | Video encoding |

## Contract tools

| Item | License | Source | Use |
|---|---|---|---|
| Foundry | MIT or Apache-2.0 | `README.md` | Contract tests, local anvil. Not bundled |
| forge-std v1.17.0 | MIT or Apache-2.0 | `README.md` | Contract tests. Installed by command |

## Prototypes, not in the CrashLab flow

| Item | License | Source | Use |
|---|---|---|---|
| Unitree Go2 model and `mjw_go2.onnx`, from Newton's asset repo | unknown | `policy/newton_lab/sim.py` | `policy/newton_lab` trial |
| Genesis (`genesis-world`) | 1.4.5, unknown (its package metadata gives no license) | `policy/genesis_lab/.venv` | `policy/genesis_lab` trial |
| NVIDIA SimFoundry | Apache-2.0 for its own code | `policy/simfoundry_lab/GPU.md` | Trial. It stopped at stage 2 on this Mac. The source is not in git |
| Depth Anything 3 large weights | CC-BY-NC-4.0 | `policy/simfoundry_lab/GPU.md` | SimFoundry stage 2 |
| FoundationPose, Any6D | non-commercial | `policy/simfoundry_lab/GPU.md` | Named by SimFoundry. Not run here |
| LIBERO | unknown | `README.md` names it, with no license | Earlier RoboBounty prototype |
| `HuggingFaceVLA/smolvla_libero` | unknown | `README.md` names it, with no license | Earlier RoboBounty prototype |
