"""Fills the library through the same loop as the chat: generate_batch.py <mode> <words>... Prints one JSON row per object. Results land in the cache."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_loop as L


def main():
    mode, words = sys.argv[1], sys.argv[2:]
    for text in words:
        if L.GO.find(text) and not text.startswith("!"):
            print(json.dumps({"words": text, "state": "cached"}), flush=True)
            continue
        text = text.lstrip("!")
        made = L.make(text, lambda line, fail=False: print("  ", line, flush=True), lambda *a: None, mode=mode)
        print(json.dumps({"words": text, "mode": mode, "state": made["state"], "sha256": made.get("sha256"), **made["stats"]}), flush=True)


if __name__ == "__main__":
    main()
