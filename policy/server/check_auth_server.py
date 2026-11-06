#!/usr/bin/env python3
"""MOCK. The site server for the auth checks only. World ID's verify call is replaced by an invented reply, so no World ID service gets a call. Never used by scripts/demo.sh."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_data
import site_world

real_verify = site_world.verify
real_context = site_world.request_context
DB = os.environ["CHECK_WORLD_DB"]  # Its own store, so a check never touches the real sign-ins.
GOOD = {"success": True, "environment": "staging", "results": [{"identifier": "proof_of_human", "success": True}, {"identifier": "device", "success": True}]}


def mock_post(result, env):
    return True, {**GOOD, **({"protocol_version": "3.0"} if result.get("protocol_version") == "3.0" else {})}


site_world.verify = lambda result, browser, saved: real_verify(result, browser, saved, db=DB, post=mock_post)
site_world.request_context = lambda browser, saved: real_context(browser, saved, db=DB)
site_data.main()
