"""Build, install and verify the AttrViz extension.

Exists because the repo and the installed extension are two different copies,
and Blender only ever runs the installed one. A green test run against the
repo says nothing about what is loaded in the app — which is exactly how a
fix can be "done" and the bug still on screen.

    python install.py            build a zip, install it, verify
    python install.py --sync     copy the source in place (fast dev loop)
    python install.py --check    verify only; exit 1 if they differ

`--check` is the one to wire into anything that claims the addon works.

Set ATTRVIZ_BLENDER to point at a specific Blender.
"""
from __future__ import annotations

import argparse
import filecmp
import glob
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(REPO, "attrviz")
BUILD = os.path.join(REPO, "build")

DEFAULT_BLENDER = [
    r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "/usr/bin/blender",
]

# Where Blender keeps user extensions, per platform. Globbed so every
# installed Blender version is found, not just the one this script knows.
CONFIG_GLOBS = [
    os.path.expanduser(
        r"~/AppData/Roaming/Blender Foundation/Blender/*/extensions/user_default/attrviz"),
    os.path.expanduser(
        "~/Library/Application Support/Blender/*/extensions/user_default/attrviz"),
    os.path.expanduser(
        "~/.config/blender/*/extensions/user_default/attrviz"),
    # Pre-extension addon layout, still worth catching: a leftover copy here
    # shadows nothing but confuses everyone.
    os.path.expanduser(
        r"~/AppData/Roaming/Blender Foundation/Blender/*/scripts/addons/attrviz"),
    os.path.expanduser("~/.config/blender/*/scripts/addons/attrviz"),
]


def blender_exe():
    exe = os.environ.get("ATTRVIZ_BLENDER")
    if exe:
        if not os.path.exists(exe):
            sys.exit(f"ATTRVIZ_BLENDER points at {exe!r}, which does not exist")
        return exe
    for cand in DEFAULT_BLENDER:
        if os.path.exists(cand):
            return cand
    sys.exit("no Blender found; set ATTRVIZ_BLENDER")


def version():
    with open(os.path.join(SRC, "blender_manifest.toml"), encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("version"):
                return line.split("=", 1)[1].strip().strip('"')
    sys.exit("no version in blender_manifest.toml")


def installs():
    found = []
    for pattern in CONFIG_GLOBS:
        found.extend(glob.glob(pattern))
    return sorted(found)


def py_files(root):
    out = set()
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith((".py", ".toml")):
                rel = os.path.relpath(os.path.join(base, name), root)
                out.add(rel.replace("\\", "/"))
    return out


def compare(dest):
    """(matches, lines) — is this install the same source as the repo?"""
    lines = []
    repo_files = py_files(SRC)
    dest_files = py_files(dest)

    missing = sorted(repo_files - dest_files)
    extra = sorted(dest_files - repo_files)
    differing = sorted(
        rel for rel in (repo_files & dest_files)
        if not filecmp.cmp(os.path.join(SRC, *rel.split("/")),
                           os.path.join(dest, *rel.split("/")), shallow=False)
    )
    for rel in missing:
        lines.append(f"    missing from install : {rel}")
    for rel in extra:
        lines.append(f"    only in install      : {rel}")
    for rel in differing:
        lines.append(f"    differs              : {rel}")

    # A __pycache__ is normal — Blender writes one every run. Only complain
    # when the bytecode is BEHIND its source, which is the case that makes an
    # updated file look like it never landed.
    cache = os.path.join(dest, "__pycache__")
    if os.path.isdir(cache):
        for pyc in glob.glob(os.path.join(cache, "*.pyc")):
            stem = os.path.basename(pyc).split(".")[0]
            src = os.path.join(dest, stem + ".py")
            if not os.path.exists(src):
                continue
            if os.path.getmtime(pyc) < os.path.getmtime(src):
                lines.append(f"    stale bytecode       : {stem}.pyc "
                             "older than its source")
    return (not lines), lines


def check(quiet=False):
    dests = installs()
    if not dests:
        print("no installed AttrViz found — nothing is loaded in Blender")
        return 1
    bad = 0
    for dest in dests:
        ok, lines = compare(dest)
        label = "MATCHES repo" if ok else "STALE"
        print(f"[{label}] {dest}")
        for line in lines:
            print(line)
        if not ok:
            bad = 1
    if bad and not quiet:
        print("\nInstalled source differs from the repo. Blender runs the "
              "install, so this is what you are actually testing.")
        print("Fix with:  python install.py        (or --sync for a fast copy)")
    return bad


def sync():
    """Copy source straight into the install. The fast dev loop.

    Not a substitute for a real build — it leaves the packaged version alone —
    but it is honest about what it did, and it clears the bytecode cache that
    would otherwise keep the old module alive.
    """
    dests = installs()
    if not dests:
        sys.exit("no installed AttrViz to sync into; run without --sync first")
    for dest in dests:
        for rel in sorted(py_files(SRC)):
            src = os.path.join(SRC, *rel.split("/"))
            dst = os.path.join(dest, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        cache = os.path.join(dest, "__pycache__")
        if os.path.isdir(cache):
            shutil.rmtree(cache, ignore_errors=True)
        print(f"synced -> {dest}")
    print("\nRestart Blender: a module already imported stays imported.")
    return 0


def build_install():
    exe = blender_exe()
    ver = version()
    os.makedirs(BUILD, exist_ok=True)
    zip_path = os.path.join(BUILD, f"attrviz-{ver}.zip")

    print(f"building {ver} ...")
    proc = subprocess.run(
        [exe, "--command", "extension", "build",
         "--source-dir", SRC, "--output-dir", BUILD],
        capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        sys.exit("extension build failed")
    if not os.path.exists(zip_path):
        found = glob.glob(os.path.join(BUILD, "attrviz-*.zip"))
        if not found:
            sys.exit(f"build produced no zip in {BUILD}")
        zip_path = max(found, key=os.path.getmtime)

    print(f"installing {os.path.basename(zip_path)} ...")
    proc = subprocess.run(
        [exe, "--command", "extension", "install-file",
         "--repo", "user_default", "--enable", zip_path],
        capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        sys.exit("extension install failed")

    for dest in installs():
        cache = os.path.join(dest, "__pycache__")
        if os.path.isdir(cache):
            shutil.rmtree(cache, ignore_errors=True)

    print()
    rc = check(quiet=True)
    print("\nRestart Blender: a module already imported stays imported.")
    return rc


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the install matches the repo; exit 1 if not")
    ap.add_argument("--sync", action="store_true",
                    help="copy source in place instead of building a zip")
    args = ap.parse_args()
    if args.check:
        return check()
    if args.sync:
        return sync()
    return build_install()


if __name__ == "__main__":
    sys.exit(main())
