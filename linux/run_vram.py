#!/usr/bin/env python3
"""Run an *existing* memtest_vulkan binary and record duration + final output.

Linux only: sends SIGINT to request the tool's own final summary, never marks
PASS just because a timer expired. Review chosen device and coverage manually.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import signal
import subprocess
import sys
import time


def _signal_group(pid, sig):
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", type=pathlib.Path, required=True, help="Path to upstream memtest_vulkan executable")
    ap.add_argument("--out", type=pathlib.Path, required=True, help="Existing run results directory")
    ap.add_argument("--seconds", type=int, default=900)
    ap.add_argument("--vulkan-device", type=int, default=None, help="Optional memtest_vulkan menu number (NOT nvidia-smi index)")
    ns = ap.parse_args()
    if sys.platform == "win32":
        ap.error("Use vendor memtest_vulkan interactively on Windows; this runner requires Linux SIGINT")
    if not 420 <= ns.seconds <= 7200:
        ap.error("--seconds must be 420..7200 (allows startup/selection overhead)")
    if ns.vulkan_device is not None and ns.vulkan_device < 1:
        ap.error("--vulkan-device must be positive Vulkan menu number")
    if not ns.out.is_dir() or not (ns.out / "run.json").is_file():
        ap.error("--out must be an existing results/TEST_... directory")
    exe = ns.bin.expanduser().resolve()
    if not exe.is_file() or not os.access(exe, os.X_OK):
        ap.error(f"Not executable: {exe}")
    logfile = ns.out / "memtest_vulkan.log"
    meta_file = ns.out / "memtest_meta.json"
    if logfile.exists() or meta_file.exists():
        ap.error("Evidence files already exist; will not overwrite")
    print("Testing VRAM. Confirm from the completed log that selected device is RTX 4090 (not llvmpipe).")
    print(f"Expected test: {ns.seconds}s; log: {logfile}", flush=True)
    start_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    start = time.monotonic()
    killed = False
    with logfile.open("w", encoding="utf-8") as fp:
        p = subprocess.Popen([str(exe)], stdout=fp, stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
                             text=True, start_new_session=True)
        if ns.vulkan_device is not None:
            try:
                p.stdin.write(str(ns.vulkan_device) + "\n")
                p.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
        try:
            p.wait(timeout=ns.seconds)
        except subprocess.TimeoutExpired:
            _signal_group(p.pid, signal.SIGINT)
            # Upstream may request a final keypress to exit after printing PASS/FAIL.
            time.sleep(1)
            if p.poll() is None:
                try:
                    p.stdin.write("\n")
                    p.stdin.flush()
                except (BrokenPipeError, OSError, ValueError):
                    pass
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                killed = True
                _signal_group(p.pid, signal.SIGTERM)
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _signal_group(p.pid, signal.SIGKILL)
                    p.wait()
        except KeyboardInterrupt:
            # Interruption before requested duration invalidates this evidence.
            _signal_group(p.pid, signal.SIGINT)
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                killed = True
                _signal_group(p.pid, signal.SIGKILL)
                p.wait()
    elapsed = time.monotonic() - start
    if p.stdin is not None:
        try:
            p.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass
    meta = {"start_utc": start_utc,
            "elapsed_seconds": round(elapsed, 2), "requested_seconds": ns.seconds,
            "process_exit_code": p.returncode, "timed_out_or_killed": killed}
    meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Finished after {elapsed:.0f}s, process exit {p.returncode}. Review last lines:")
    print("\n".join(logfile.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]))
    print("Run `python3 tools/analyze.py PATH_TO_RUN_DIR` to update report.")
    return 0 if not killed else 1


if __name__ == "__main__":
    sys.exit(main())
