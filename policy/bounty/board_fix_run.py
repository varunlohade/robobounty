"""Runs fix.py for the board, as its own process: board_fix_run.py check|preflight|run ... No file of fix.py changes.

Two things differ from fix.py run: every sandbox run has live frames off, since a sandbox has no graphics connection and a picture never changes a result. And no LLM can start here: the board always passes --patch.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "crashlab"))
sys.path.insert(0, str(HERE.parent / "server"))
import fix as F
import pack_job

_setup = F.sandbox_setup5


def _no_frames(pack, run_dir):
    reads, env = _setup(pack, run_dir)
    return reads, {**env, pack_job.NO_FRAMES_ENV: "1"}


def _no_llm(*_, **__):
    raise SystemExit("The board never calls an LLM.")


F.sandbox_setup5 = _no_frames
F.llm_edit = _no_llm


def main():
    command = sys.argv[1]
    if command == "check":
        pack, path, reply = sys.argv[2:5]
        Path(reply).write_text(json.dumps({"reasons": F.validate5(pack, Path(path).read_text(), F.PACK5[pack]["file"], constants_only=pack == "inspection")}))
        return 0
    if command == "preflight":
        pack, controller, world_file, out, reply = sys.argv[2:7]
        Path(reply).write_text(json.dumps(F.trial5(pack, controller, json.loads(Path(world_file).read_text()), Path(out), False)))
        return 0
    if command == "run":
        sys.argv = ["fix.py", "run", *sys.argv[2:]]
        if "--patch" not in sys.argv:
            raise SystemExit("The board needs --patch.")
        return F.main()
    raise SystemExit("check, preflight or run")


if __name__ == "__main__":
    sys.exit(main())
