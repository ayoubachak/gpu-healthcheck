#!/usr/bin/env python3
"""Turn recorded RTX 4090 test evidence into a report.

Missing or short evidence is never upgraded to PASS; physical inspection remains manual.
"""
import argparse
import csv
import json
import pathlib
import re
import sys
from statistics import mean


# gpu-burn -m 85% should reserve roughly 20 GB on an idle 24 GB card.
MIN_STRESS_VRAM_MIB = 16000


def burn_result(path, idx):
    if not path.is_file():
        return "MISSING", "gpu-burn log missing"
    txt = path.read_text(encoding="utf-8", errors="replace")
    if re.search(rf"GPU\s+{idx}\s*:\s*FAULTY", txt, re.I) or re.search(r"\berrors\s*:\s*[1-9]\d*\b", txt, re.I):
        return "FAIL", "gpu-burn reported incorrect calculations / FAULTY"
    if re.search(r"\bCUDA_ERROR\b|couldn.t init|\bfailed\b|segmentation fault|illegal memory access", txt, re.I):
        return "INCONCLUSIVE", "gpu-burn runtime or initialization failure; investigate host"
    if re.search(rf"GPU\s+{idx}\s*:\s*OK\b", txt, re.I):
        return "PASS", "gpu-burn reported final GPU OK; verify run duration and telemetry"
    return "INCONCLUSIVE", "No verifiable gpu-burn final status"


def vram_result(path):
    if not path.is_file():
        return "MISSING", "memtest_vulkan.log missing"
    txt = path.read_text(encoding="utf-8", errors="replace")
    if re.search(r"\berror found\b|\berrors? detected\b|\btesting FAILED\b|\bFAIL(?:ED)?\b", txt, re.I):
        return "FAIL", "memtest_vulkan reported an error"
    if re.search(r"no any errors[^\n]*testing PASSed", txt, re.I):
        return "PASS", "memtest_vulkan emitted final clean marker"
    return "INCONCLUSIVE", "No clean completion marker (Ctrl+C and wait for summary)"


def vram_evidence(folder):
    log = folder / "memtest_vulkan.log"
    state, reason = vram_result(log)
    if state != "PASS":
        return state, reason
    txt = log.read_text(encoding="utf-8", errors="replace")
    # The line printed when a device is actually being tested, for example:
    #   Testing 1: Bus=0x01:00 DevId=0x2684   24GB NVIDIA GeForce RTX 4090
    selected = bool(re.search(r"Testing\s+\d+\s*:[^\n]*\bRTX\s+4090\b", txt, re.I))
    if not selected:
        return "INCONCLUSIVE", "Cannot prove RTX 4090 was the selected Vulkan test device"
    meta_path = folder / "memtest_meta.json"
    if not meta_path.is_file():
        return "INCONCLUSIVE", "Elapsed test time unverified; use linux/run_vram.py"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        seconds = float(meta.get("elapsed_seconds", 0))
        if seconds < 360:
            return "INCONCLUSIVE", f"Memory test lasted only {seconds:.0f}s (<360s required)"
        if meta.get("timed_out_or_killed", False):
            return "INCONCLUSIVE", "Vulkan tester required forced termination"
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return "INCONCLUSIVE", "Invalid memtest_meta.json"
    return "PASS", f"Vulkan selected RTX 4090 and ran {seconds:.0f}s; allocation coverage still needs manual review"


def telemetry_stats(path):
    if not path.is_file():
        return None
    temps, powers, memory, usage = [], [], [], []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            for key, dest in [("temp_core_C", temps), ("power_W", powers),
                              ("memory_used_MiB", memory), ("gpu_util_pct", usage)]:
                try:
                    dest.append(float(row[key].strip()))
                except (ValueError, TypeError, KeyError, AttributeError):
                    pass
    if not temps:
        return None
    return {"samples": len(temps), "max_core_C": max(temps),
            "avg_core_C": round(mean(temps), 1), "max_power_W": max(powers) if powers else None,
            "max_allocated_vram_MiB": max(memory) if memory else None,
            "max_gpu_util_pct": max(usage) if usage else None}


def examine(folder, require_ai=False):
    runfile = folder / "run.json"
    if not runfile.is_file():
        raise FileNotFoundError(f"Missing {runfile}; no hardware-run record")
    run = json.loads(runfile.read_text(encoding="utf-8"))
    idx = run.get("gpu_index", 0)
    checks, warnings, informational = {}, [], []

    identity_good = bool(re.search(r"\bRTX\s+4090\b", str(run.get("gpu_name", "")), re.I)) and int(run.get("memory_total_mib", 0)) >= 23000
    checks["device_identity"] = {"status": "PASS" if identity_good else "FAIL",
                                 "detail": f"{run.get('gpu_name', 'unknown')} ({run.get('memory_total_mib', '?')} MiB)"}
    for name in ("fp32", "tensor"):
        stage = next((s for s in run.get("stages", []) if s.get("name") == name), None)
        if stage is None:
            checks[f"gpu_burn_{name}"] = {"status": "MISSING", "detail": "No stage record"}
            continue
        state, detail = burn_result(folder / stage.get("log", f"gpu_burn_{name}.log"), idx)
        if state != "FAIL":
            if stage.get("exit_code") != 0:
                state, detail = "INCONCLUSIVE", f"Process exited {stage.get('exit_code')}: {detail}"
            if stage.get("thermal_stop"):
                state, detail = "INCONCLUSIVE", "Thermal safety stop: " + detail
            elapsed = float(stage.get("duration_actual_seconds", 0))
            expected = float(stage.get("duration_requested_seconds", 0))
            if expected <= 0 or elapsed < expected * 0.90:
                state, detail = "INCONCLUSIVE", f"Only {elapsed:.0f}/{expected:.0f}s elapsed: {detail}"
        checks[f"gpu_burn_{name}"] = {"status": state, "detail": detail}

    vstate, vdetail = vram_evidence(folder)
    checks["vulkan_vram"] = {"status": vstate, "detail": vdetail}
    stat = telemetry_stats(folder / "telemetry.csv")
    if not stat or stat["samples"] < 3:
        checks["telemetry"] = {"status": "INCONCLUSIVE", "detail": "Missing or <3 sensor samples"}
    elif run.get("thermal_stop") or stat["max_core_C"] >= run.get("core_temp_cutoff_C", 88):
        checks["telemetry"] = {"status": "INCONCLUSIVE", "detail": f"Temperature guard reached: {stat['max_core_C']:.1f} C"}
    elif run.get("sensor_errors"):
        checks["telemetry"] = {"status": "INCONCLUSIVE", "detail": "Sensor logger reported errors"}
    else:
        checks["telemetry"] = {"status": "PASS", "detail": f"{stat['samples']} samples; max core {stat['max_core_C']:.1f} C"}
        if stat["max_core_C"] >= 85:
            warnings.append("Core GPU temperature >=85 C: review cooling and airflow")
        if (stat.get("max_allocated_vram_MiB") or 0) < MIN_STRESS_VRAM_MIB:
            checks["telemetry"] = {"status": "INCONCLUSIVE", "detail": f"Peak allocated VRAM under {MIN_STRESS_VRAM_MIB} MiB; stress coverage too low"}
            warnings.append(f"VRAM allocation under {MIN_STRESS_VRAM_MIB} MiB during compute stage: rerun on an idle GPU")

    ai_file = folder / "torch_ai.json"
    if ai_file.is_file():
        try:
            ai = json.loads(ai_file.read_text(encoding="utf-8"))
            if str(ai.get("status", "")).startswith("PASS"):
                status = "PASS"
            elif any(isinstance(c, dict) and c.get("pass") is False
                     for c in ai.get("checks", {}).values()):
                status = "FAIL"
            elif "VRAM pattern test found" in str(ai.get("error", "")):
                status = "FAIL"
            else:
                status = "INCONCLUSIVE"  # CUDA missing / environment error need not mean bad hardware
            checks["pytorch_ai"] = {"status": status, "detail": str(ai.get("error", ai.get("status", "unknown")))}
        except (ValueError, OSError):
            checks["pytorch_ai"] = {"status": "INCONCLUSIVE", "detail": "Invalid PyTorch JSON"}
    else:
        checks["pytorch_ai"] = {"status": "MISSING" if require_ai else "OPTIONAL", "detail": "No torch_ai.json"}

    kernel_log = folder / "kernel_gpu.log"
    if kernel_log.is_file():
        txt = kernel_log.read_text(encoding="utf-8", errors="replace")
        if not txt.strip():
            checks["driver_xid"] = {"status": "INCONCLUSIVE", "detail": "Kernel excerpt empty: cannot verify collection succeeded"}
        elif re.search(r"\bNVRM:\s*Xid\b|fallen off the bus", txt, re.I):
            checks["driver_xid"] = {"status": "INCONCLUSIVE", "detail": "GPU Xid / fallen-off-bus detected: correlate time and test host"}
        else:
            checks["driver_xid"] = {"status": "PASS", "detail": "No Xid found in supplied kernel excerpt"}
    else:
        checks["driver_xid"] = {"status": "MISSING", "detail": "No kernel excerpt (may require sudo)"}

    informational.append("Vulkan tests may cover less than 24 GB depending on driver allocation.")

    required = []
    for name, item in checks.items():
        # The optional AI check only counts when it ran or was explicitly required.
        if name == "pytorch_ai" and not require_ai and item["status"] == "OPTIONAL":
            continue
        required.append(item["status"])

    if "FAIL" in required:
        overall = "RED FLAG - INVESTIGATE OR REJECT"
        code = 2
    elif any(status != "PASS" for status in required):
        overall = "INCOMPLETE - NO BUY CLEARANCE"
        code = 1
    else:
        overall = "SOFTWARE CHECKS PASSED - PHYSICAL INSPECTION STILL REQUIRED"
        code = 0
    return {"verdict": overall, "exit_code": code, "checks": checks, "telemetry": stat,
            "warnings": warnings, "notes": informational, "profile": run.get("mode", "unknown")}


def write_reports(folder, result):
    (folder / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = ["# Used RTX 4090 evaluation", "", f"**Verdict: {result['verdict']}**", "", "| Check | Result | Evidence |", "|---|---|---|"]
    for label, item in result["checks"].items():
        detail = str(item["detail"]).replace("|", "/").replace("\n", " ")
        lines.append(f"| {label} | {item['status']} | {detail} |")
    lines += ["", "## Telemetry", "", "```json", json.dumps(result["telemetry"], indent=2), "```", "", "## Warnings and caveats", ""]
    lines += ["- " + x for x in result["warnings"] + result["notes"]]
    lines += ["", "## Manual checks", "", "- [ ] Inspect the unpowered 16-pin socket, cables, fans and board for damage",
              "- [ ] Verify board model, serial, invoice, warranty and repair history",
              "- [ ] Confirm the VRAM tester selected the correct GPU, allocated meaningful memory and showed zero errors",
              "- [ ] Compare performance with cards of the same model and power limit; check for throttling and display artifacts",
              "- [ ] Retest on a known-good PSU and host if any error appears"]
    (folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(result["verdict"] + f"\nReports: {folder / 'report.md'} and {folder / 'report.json'}")


def analyze(folder, require_ai=False):
    result = examine(folder, require_ai=require_ai)
    write_reports(folder, result)
    return result["verdict"]


def main():
    ap = argparse.ArgumentParser(description="Generate a used RTX 4090 health report")
    ap.add_argument("folder", type=pathlib.Path)
    ap.add_argument("--require-ai", action="store_true", help="Treat missing PyTorch benchmark as incomplete")
    ns = ap.parse_args()
    try:
        result = examine(ns.folder, require_ai=ns.require_ai)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    write_reports(ns.folder, result)
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
