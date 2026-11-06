"""A short quiz for new engineers, written from the window and inspection robots. The server grades it, and the answers never leave this file through a route.

Six questions from the bank. Five right passes. A fail waits, and then gets new questions. Passing a quiz is not proof of skill: the bank is small and a person can look things up.
Run: screener.py key prints the answers, for a check that has to pass the quiz in a browser.
"""
import json
import random
import sys
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import site_auth as A

COUNT, PASS_MARK = 6, 5
RETRY_S = 120
OPEN_S = 1800
FAILED = "Not this time. You can try again in 2 minutes, with new questions."
# (id, question, choices, the right choice)
BANK = [
    ("wind_resume", "A window robot pauses at 10 m/s roof wind. It resumes below 7 m/s after a wait. Why two numbers?", ["It stops the robot starting and stopping as wind hovers near one limit", "The sensor reads two winds", "It saves battery", "The judge asks for it"], 0),
    ("wind_hold_verdict", "A run ends in a wind hold, and the robot is still attached. How should you read it?", ["A safe hold: the robot chose to stop, and it is not a crash", "The robot passed the job", "The robot detached", "The simulator failed"], 0),
    ("hold_tradeoff", "A fix lowers the wind pause limit. Safe holds go up, and coverage goes down. What is the honest summary?", ["The fix trades finished work for caution", "The fix is a pure gain", "The robot is now faster", "The wind changed"], 0),
    ("seal_leak", "Suction pressure falls while fan power is at its top, on a cracked glass joint. What is the likely cause?", ["The seal leaks, so more fan cannot hold the pressure", "The battery is full", "The camera is dirty", "The route is too short"], 0),
    ("full_suction_detach", "A robot detaches at full suction. What does that tell you about a fix that only asks for more suction?", ["It cannot help, because no suction is left to add", "It always helps", "It helps only in wind", "It helps only when dry"], 0),
    ("low_pressure_action", "Pressure drops under the safe limit while cleaning. What should a controller do first?", ["Stop and back away to where the seal held", "Drive faster over the bad area", "Report the job done", "Turn the fan off"], 0),
    ("retreat_limit", "Why cap the number of retreats per lane?", ["Without a cap the robot can repeat the same retreat until the time limit", "Retreats use no time", "The tether needs it", "The cap makes the fan stronger"], 0),
    ("track_slip", "On wet glass the tracks turn, and the position estimate moves up, but the robot slides down. What is going on?", ["Track slip: wheel odometry counts motion that did not happen", "The glass moved", "The wind sensor failed", "The robot is climbing well"], 0),
    ("pivot_sag", "A pivot turn skids the tracks and the body sags. What keeps lanes aligned after each turn?", ["Measure the error and correct it, not assume the turn was clean", "Turn faster", "Remove the side step", "Raise the coverage limit"], 0),
    ("false_done", "The robot reports done, but the judge counts less coverage than the robot claimed. What is this failure?", ["False done: the robot's own count is wrong, so its report cannot be trusted", "A wind hold", "A detach", "A pass"], 0),
    ("stalled", "A robot sits still at the end of a run, with no wind and a good battery. Which question comes first?", ["Which controller state is it in, and what is it waiting for?", "How can we hide the row?", "Is the glass clean enough to skip it?", "Can we extend the time limit?"], 0),
    ("anymal_pipe", "ANYmal falls at a low pipe across its route. The policy is a trained walker, and the route follower is ours. Which change can a controller fix actually make?", ["Change the route or speed commands the follower sends", "Retrain the policy weights inside the fix", "Edit the judge's fall rule", "Lower gravity"], 0),
    ("anymal_slow", "You slow ANYmal's command to 0.3 m/s to be careful, and it stops making progress. What is the likely reason?", ["This walking policy barely moves at such low commands", "The route is closed", "The judge has a speed rule", "The battery is low"], 0),
    ("anymal_turn", "ANYmal is far off its heading, and walking while turning makes it drift. What is a sound control choice?", ["Stop walking forward and turn in place past a heading limit", "Raise the speed", "Skip the waypoint and report it passed", "Turn off the heading gain"], 0),
    ("oily_floor", "ANYmal passes on dry steel, and falls on the same ramp when it is oily. What changed?", ["Friction: the same command now asks for more grip than the floor gives", "The ramp's length", "The policy's weights", "The judge's limit"], 0),
    ("judge_reason", "The judge says: \"The robot slid 0.312 m in one slide at 41.2 s.\" Where do you look first?", ["The recorded run just before 41.2 s, with the pressure and track commands", "The login page", "The final coverage only", "The first second of the run"], 0),
    ("one_world", "A fix passes the one failing world you were shown. Why does the board also run hidden worlds?", ["A fix can overfit the world it saw, so unseen worlds test whether it carries over", "To use more CPU", "To change the judge", "To slow engineers down"], 0),
    ("worse_elsewhere", "Your fix cures the slip but makes two worlds that passed before fail. What is the right call?", ["Treat it as a regression, and find why those worlds got worse", "Ship it: one failure is fixed", "Delete those worlds", "Re-run until they pass"], 0),
    ("flaky", "The same world and seed gives two different results on two runs. What does that mean first?", ["The run is not repeatable, so find the source before trusting either result", "The fix works half the time, which is fine", "The first result counts", "The judge is fair by chance"], 0),
    ("sim_only", "A fix passes every simulated world here. What can you claim?", ["It passed in this simulation, and it is unchecked on a real robot", "It is safe on a real robot", "It is certified", "It will never fail"], 0),
]
BY_ID = {q[0]: q for q in BANK}


def _shown(ids):
    out = []
    for qid in ids:
        _, words, choices, _ = BY_ID[qid]
        order = sorted(range(len(choices)), key=lambda i: A._sha(f"{qid}|{i}"))  # A fixed mixed order, so the right choice is not always first.
        out.append({"id": qid, "question": words, "choices": [{"n": i, "text": choices[i]} for i in order]})
    return out


def start(account_id, db=None, now=None):
    """The open questions of this account, or new ones. Reloading does not give new questions, so a person cannot fish for easy ones."""
    now = time.time() if now is None else now
    with closing(A._open(db)) as d:
        row = d.execute("SELECT questions, started_at, retry_at FROM screen WHERE account_id=?", (account_id,)).fetchone()
        if row and row[2] and row[2] > now:
            raise A.Refused(429, "screener_wait", FAILED)
        if row and row[0] and now - row[1] < OPEN_S:
            return {"questions": _shown(json.loads(row[0])), "pass_mark": PASS_MARK}
        ids = random.SystemRandom().sample([q[0] for q in BANK], COUNT)
        d.execute("INSERT OR REPLACE INTO screen VALUES (?,?,?,?)", (account_id, json.dumps(ids), now, 0))
    return {"questions": _shown(ids), "pass_mark": PASS_MARK}


def grade(account_id, answers, db=None, now=None):
    """One grade per set of questions. The reply holds the count, and never which answer was wrong."""
    now = time.time() if now is None else now
    with closing(A._open(db)) as d:
        row = d.execute("SELECT questions FROM screen WHERE account_id=?", (account_id,)).fetchone()
        ids = json.loads(row[0]) if row and row[0] else None
        if not ids or not isinstance(answers, dict) or set(answers) != set(ids) or not all(isinstance(answers[q], int) and not isinstance(answers[q], bool) for q in ids):
            raise A.Refused(400, "screener_shape", "Answer each question.")
        taken = d.execute("UPDATE screen SET questions=NULL, retry_at=? WHERE account_id=? AND questions=?", (now + RETRY_S, account_id, row[0])).rowcount
        if taken != 1:
            raise A.Refused(400, "screener_shape", "Answer each question.")
        score = sum(answers[q] == BY_ID[q][3] for q in ids)
        passed = score >= PASS_MARK
        if passed:
            d.execute("UPDATE accounts SET screened_at=? WHERE id=? AND role='engineer'", (now, account_id))
            d.execute("DELETE FROM screen WHERE account_id=?", (account_id,))
    return {"passed": passed, "score": score, "of": COUNT, "words": "Screened. A short quiz is not proof of skill." if passed else FAILED}


if __name__ == "__main__":
    if sys.argv[1:] != ["key"]:
        raise SystemExit(__doc__)
    print(json.dumps({q[0]: q[3] for q in BANK}))
