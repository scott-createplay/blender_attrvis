"""The driver — launches Blender once per scenario, then checks the results.

Runs OUTSIDE Blender, with the system Python. This is the Playwright-shaped
half: an external orchestrator driving a real application.

  python dev_tasks/015_docs_capture/run_captures.py            # capture all
  python dev_tasks/015_docs_capture/run_captures.py menu_scope # one
  python dev_tasks/015_docs_capture/run_captures.py --check    # gate on drift

`--check` compares each gated scenario against `baselines/<name>.png` and
exits non-zero on any mismatch. Ungated scenarios (cascades, C7b) are captured
and reported but never fail the run.

Set ATTRVIZ_BLENDER to override the Blender path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import scenarios  # noqa: E402

OUT = os.path.join(HERE, "out", "stage1")
BASELINES = os.path.join(HERE, "baselines")

# Measured floor: two runs of one scenario differ by up to ~36px of
# antialiasing noise. Byte equality is stricter than Playwright's own
# toHaveScreenshot, which uses maxDiffPixels. 200 leaves headroom over the
# noise while still catching a real UI change, which moves thousands.
MAX_DIFF_PX = 200

DEFAULT_BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"


def blender_exe():
    exe = os.environ.get("ATTRVIZ_BLENDER", DEFAULT_BLENDER)
    if not os.path.exists(exe):
        sys.exit(f"Blender not found at {exe!r}; set ATTRVIZ_BLENDER")
    return exe


def md5(path):
    with open(path, "rb") as fh:
        return hashlib.md5(fh.read()).hexdigest()


def run_one(scen, exe, out=None):
    x, y, w, h = scen["window"]
    cmd = [exe, "--factory-startup",
           "-p", str(x), str(y), str(w), str(h),
           os.path.join(REPO, scen["blend"]),
           "--python", os.path.join(HERE, "capture.py")]
    env = dict(os.environ, ATTRVIZ_SCENARIO=scen["name"],
               ATTRVIZ_OUT=out or OUT)
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    return proc.returncode, proc.stdout


def compare_pairs(pairs, exe):
    """Compare image pairs by PIXELS, not bytes. One background Blender does
    the decoding, so this driver needs no image library."""
    if not pairs:
        return {}
    tmp = os.path.join(HERE, "out")
    os.makedirs(tmp, exist_ok=True)
    man, res = os.path.join(tmp, "_pairs.json"), os.path.join(tmp, "_cmp.json")
    with open(man, "w", encoding="utf-8") as fh:
        json.dump(pairs, fh)
    subprocess.run([exe, "--background", "--factory-startup",
                    "--python", os.path.join(HERE, "compare.py"),
                    "--", man, res], capture_output=True, text=True)
    with open(res, encoding="utf-8") as fh:
        return json.load(fh)


def verdict(scen, cmp_row):
    """Tolerance is per-scenario; MAX_DIFF_PX is the default floor."""
    limit = scen.get("max_diff_px", MAX_DIFF_PX)
    if not cmp_row or cmp_row.get("error"):
        return False, (cmp_row or {}).get("error", "no comparison"), limit
    changed = cmp_row["changed"]
    return changed <= limit, f"{changed} px changed (limit {limit})", limit


def selfcheck(chosen, exe):
    """Run each scenario twice; a scenario that differs from itself must not
    be gated. Returns non-zero if a *gated* scenario proves unstable."""
    passes = []
    for tag in ("selfcheck_a", "selfcheck_b"):
        out = os.path.join(HERE, "out", tag)
        os.makedirs(out, exist_ok=True)
        got = {}
        for scen in chosen:
            code, _ = run_one(scen, exe, out)
            img = os.path.join(out, scen["name"] + ".png")
            got[scen["name"]] = img if code == 0 and os.path.exists(img) \
                else None
        passes.append(got)

    pairs = [{"name": s["name"], "a": passes[0][s["name"]],
              "b": passes[1][s["name"]]}
             for s in chosen
             if passes[0][s["name"]] and passes[1][s["name"]]]
    cmp_out = compare_pairs(pairs, exe)

    bad = []
    print("\n--- self-consistency (two passes, pixel diff) ---")
    for scen in chosen:
        name = scen["name"]
        gate = "gated" if scen["gated"] else "ungated"
        ok, detail, _limit = verdict(scen, cmp_out.get(name))
        label = "STABLE  " if ok else "UNSTABLE"
        print(f"{label} {name:24s} {gate:8s} {detail}")
        if not ok and scen["gated"]:
            bad.append(name)
    if bad:
        print(f"\ngated but unstable: {', '.join(bad)} — ungate or fix")
        return 1
    print("\nevery gated scenario is stable")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="scenario names (default: all)")
    ap.add_argument("--check", action="store_true",
                    help="fail on drift from baselines/")
    ap.add_argument("--bless", action="store_true",
                    help="copy current output into baselines/")
    ap.add_argument("--selfcheck", action="store_true",
                    help="run each scenario TWICE and report whether it is "
                         "stable enough to gate on")
    args = ap.parse_args()

    exe = blender_exe()
    os.makedirs(OUT, exist_ok=True)
    chosen = ([scenarios.by_name(n) for n in args.names]
              if args.names else scenarios.SCENARIOS)

    if args.selfcheck:
        # Whether a scenario may be gated is an empirical question, not a
        # guess: menu_root looked stable on one sample and was not. Two passes
        # into separate directories, compared.
        return selfcheck(chosen, exe)

    results = []
    for scen in chosen:
        code, out = run_one(scen, exe)
        img = os.path.join(OUT, scen["name"] + ".png")
        ok = code == 0 and os.path.exists(img)
        results.append((scen, ok, code, img, out))
        print(f"{'ok  ' if ok else 'FAIL'} {scen['name']:24s} exit={code}")
        if not ok:
            tail = [ln for ln in out.splitlines() if "[capture]" in ln]
            for line in tail[-6:]:
                print(f"       {line}")

    if args.bless:
        os.makedirs(BASELINES, exist_ok=True)
        for scen, ok, _code, img, _out in results:
            if ok and scen["gated"]:
                dst = os.path.join(BASELINES, scen["name"] + ".png")
                with open(img, "rb") as src, open(dst, "wb") as fh:
                    fh.write(src.read())
                print(f"blessed {scen['name']}")
        return 0

    failures = [s["name"] for s, ok, *_ in results if not ok]

    if args.check:
        print("\n--- drift check (gated scenarios only) ---")
        pairs = []
        for scen, ok, _code, img, _out in results:
            name = scen["name"]
            base = os.path.join(BASELINES, name + ".png")
            if not scen["gated"]:
                print(f"skip {name:24s} ungated (C7b)")
                continue
            if not ok:
                continue
            if not os.path.exists(base):
                print(f"MISS {name:24s} no baseline - run --bless")
                failures.append(name)
            else:
                pairs.append({"name": name, "a": img, "b": base})
        cmp_out = compare_pairs(pairs, exe)
        for scen, ok, _code, img, _out in results:
            name = scen["name"]
            if not scen["gated"] or not ok or name not in cmp_out:
                continue
            passed, detail, _limit = verdict(scen, cmp_out[name])
            print(f"{'same ' if passed else 'DRIFT'} {name:24s} {detail}")
            if not passed:
                failures.append(name)

    if failures:
        print(f"\nFAILED: {', '.join(sorted(set(failures)))}")
        return 1
    print("\nall good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
