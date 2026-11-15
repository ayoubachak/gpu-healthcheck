#!/usr/bin/env python3
"""Orchestrate established gpu-burn tests and NVIDIA telemetry. Stdlib only."""
import argparse
import csv
import datetime as dt
import json
import pathlib
import re
import signal
import subprocess
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIELDS = "timestamp,index,name,memory.total,memory.used,temperature.gpu,utilization.gpu,power.draw,clocks.sm,clocks.mem,pstate"
COLUMNS = ["timestamp", "index", "name", "memory_total_MiB", "memory_used_MiB", "temp_core_C",
           "gpu_util_pct", "power_W", "sm_clock_MHz", "mem_clock_MHz", "pstate"]


def smi_query(idx, fields):
    p = subprocess.run(["nvidia-smi", "-i", str(idx), f"--query-gpu={fields}",
                        "--format=csv,noheader,nounits"], text=True, capture_output=True, timeout=15)
    if p.returncode != 0:
        raise RuntimeError("nvidia-smi query failed: " + (p.stderr.strip() or p.stdout.strip()))
    rows = list(csv.reader(p.stdout.strip().splitlines()))
    if len(rows) != 1:
        raise RuntimeError(f"Expected one GPU record, found {len(rows)}")
    return [x.strip() for x in rows[0]]


class SensorLogger:
    def __init__(self, idx, output, cutoff):
        self.idx, self.output, self.cutoff = idx, output, cutoff
        self.stop_event = threading.Event()
        self.hot = False
        self.errors = []
        self.process = None
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def loop(self):
        with self.output.open("w", encoding="utf-8", newline="") as fh:
            wr = csv.writer(fh)
            wr.writerow(COLUMNS)
            while not self.stop_event.is_set():
                try:
                    row = smi_query(self.idx, FIELDS)
                    if len(row) == len(COLUMNS):
                        wr.writerow(row)
                        fh.flush()
                        try:
                            temp = float(row[5])
                            if temp >= self.cutoff and not self.hot:
                                self.hot = True
                                print(f"\nHIGH TEMPERATURE: {temp:.0f} C >= {self.cutoff} C. Stopping load.",
                                      file=sys.stderr, flush=True)
                                if self.process is not None and self.process.poll() is None:
                                    self.process.terminate()
                        except ValueError:
                            pass
                    else:
                        self.errors.append(f"Unexpected fields: {row!r}")
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    self.errors.append(str(exc))
                self.stop_event.wait(2)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)


def run_stage(args, name, seconds, addflags, sensor, output):
    command = [str(args.gpu_burn), "-i", str(args.gpu), "-m", "85%", *addflags, str(seconds)]
    logfile = output / f"gpu_burn_{name}.log"
    print(f"\nRunning {name} for {seconds}s: {' '.join(command)}", flush=True)
    start = time.monotonic()
    with logfile.open("w", encoding="utf-8") as fp:
        fp.write("command: " + " ".join(command) + "\n\n")
        fp.flush()
        p = subprocess.Popen(command, cwd=str(args.gpu_burn.parent), stdout=fp, stderr=subprocess.STDOUT)
        sensor.process = p
        try:
            code = p.wait(timeout=seconds + 120)
        except subprocess.TimeoutExpired:
            print(f"{name}: process overran expected duration; terminating", file=sys.stderr)
            p.terminate()
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            code = p.returncode
        finally:
            sensor.process = None
    elapsed = round(time.monotonic() - start, 1)
    return {"name": name, "duration_requested_seconds": seconds, "duration_actual_seconds": elapsed,
            "exit_code": code, "log": logfile.name, "thermal_stop": sensor.hot}


def main():
    parser = argparse.ArgumentParser(description="RTX 4090 tested purchase runner (stock settings)")
    parser.add_argument("--gpu", type=int, default=0, help="nvidia-smi GPU index")
    parser.add_argument("--mode", choices=["quick", "full"], default="quick")
    parser.add_argument("--gpu-burn", type=pathlib.Path, default=ROOT / "external/gpu-burn/gpu_burn")
    parser.add_argument("--cutoff", type=int, default=88, help="Core GPU temperature safety cutoff C (default: 88)")
    args = parser.parse_args()
    if args.gpu < 0 or not 75 <= args.cutoff <= 90:
        parser.error("--gpu must be >=0 and --cutoff must be within 75..90")
    args.gpu_burn = args.gpu_burn.expanduser().resolve()
    if not args.gpu_burn.is_file() or not args.gpu_burn.stat().st_mode & 0o111:
        parser.error(f"Executable gpu-burn missing: {args.gpu_burn}. See linux/README.md")
    try:
        identity = smi_query(args.gpu, "index,name,memory.total")
    except Exception as exc:
        parser.error(str(exc))
    print("Detected GPU:", identity)
    try:
        vram_mib = int(float(identity[2]))
    except ValueError:
        parser.error(f"Cannot parse VRAM amount from {identity}")
    if "RTX 4090" not in identity[1] or vram_mib < 23000:
        parser.error("GPU identity is NOT an RTX 4090 with approximately 24GB VRAM. Refusing test.")
    out = ROOT / "results" / f"TEST_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_GPU{args.gpu}"
    out.mkdir(parents=True, exist_ok=False)
    print("Output:", out)
    snapshot = subprocess.run(["nvidia-smi", "-i", str(args.gpu), "-q"], text=True, capture_output=True)
    (out / "preflight.txt").write_text(snapshot.stdout + "\n" + snapshot.stderr, encoding="utf-8")
    record = {"gpu_index": args.gpu, "gpu_name": identity[1], "memory_total_mib": vram_mib,
              "mode": args.mode, "start_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "core_temp_cutoff_C": args.cutoff, "stages": [], "notes": ["memtest_vulkan must be run separately and logged to this directory."]}
    sensor = SensorLogger(args.gpu, out / "telemetry.csv", args.cutoff)
    sensor.start()
    lengths = (240, 240) if args.mode == "quick" else (900, 900)
    try:
        for name, seconds, flags in [("fp32", lengths[0], []), ("tensor", lengths[1], ["-tc"])]:
            if sensor.hot:
                break
            record["stages"].append(run_stage(args, name, seconds, flags, sensor, out))
    except KeyboardInterrupt:
        record["notes"].append("User interrupted a stage. Not a completed test.")
        if sensor.process is not None and sensor.process.poll() is None:
            sensor.process.terminate()
            try:
                sensor.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                sensor.process.kill()
    finally:
        sensor.stop()
        record["sensor_errors"] = sensor.errors
        record["thermal_stop"] = sensor.hot
        record["end_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        (out / "run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "tools/analyze.py"), str(out)], check=False)
    print(f"\nNext required test: memtest_vulkan on this RTX 4090. Save output as {out / 'memtest_vulkan.log'} then rerun the analyzer.")


if __name__ == "__main__":
    main()
