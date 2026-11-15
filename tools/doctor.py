#!/usr/bin/env python3
"""Read-only readiness checks. Places no load on the GPU."""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _smi(query, index):
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None, "nvidia-smi not found"
    try:
        p = subprocess.run([exe, "-i", str(index), f"--query-gpu={query}",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if p.returncode:
        return None, p.stderr.strip() or "nvidia-smi failed"
    return [s.strip() for s in p.stdout.strip().split(",")], None


def check_driver(index):
    parts, err = _smi("index,name,memory.total,driver_version,pci.bus_id", index)
    if parts is None:
        status = "MISSING" if err == "nvidia-smi not found" else "ERROR"
        return {"status": status, "detail": err}
    if len(parts) != 5:
        return {"status": "ERROR", "detail": "Unexpected nvidia-smi CSV output"}
    try:
        total = int(parts[2])
    except ValueError:
        return {"status": "ERROR", "detail": "Unable to parse VRAM capacity"}
    ready = bool(re.search(r"\bRTX\s+4090\b", parts[1], re.I)) and total >= 23000
    return {"status": "READY" if ready else "WRONG_GPU",
            "detail": {"gpu": parts[1], "vram_mib": total,
                       "driver": parts[3], "pci_bus_id": parts[4]}}


def check_pcie(index):
    """Informational: an idle GPU may report a narrower link than its maximum."""
    parts, err = _smi("pcie.link.gen.current,pcie.link.gen.max,"
                      "pcie.link.width.current,pcie.link.width.max", index)
    if parts is None:
        return {"status": "UNKNOWN", "detail": err}
    if len(parts) != 4:
        return {"status": "UNKNOWN", "detail": "Unexpected nvidia-smi CSV output"}
    gen, gen_max, width, width_max = parts
    detail = f"PCIe {gen}.0 x{width} (max {gen_max}.0 x{width_max})"
    if (gen, width) != (gen_max, width_max):
        detail += "; verify slot, riser and idle link state"
    return {"status": "INFO", "detail": detail}


def main():
    ap = argparse.ArgumentParser(description="Check prerequisites without stressing the GPU")
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.gpu < 0:
        ap.error("GPU must be nonnegative")
    checks = {
        "nvidia_driver": check_driver(args.gpu),
        "pcie_link": check_pcie(args.gpu),
        "gpu_burn_binary": {"status": "PRESENT" if (ROOT / "external/gpu-burn/gpu_burn").exists() else "NOT_INSTALLED"},
        "vulkan_memory_binary": {"status": "PRESENT" if (ROOT / "external/memtest_vulkan").exists() else "NOT_INSTALLED"},
        "pytorch": {"status": "OPTIONAL", "detail": "Install CUDA-enabled PyTorch separately"},
    }
    if args.json:
        print(json.dumps(checks, indent=2))
    else:
        for name, check in checks.items():
            print(f"{name:22s}: {check['status']}  {check.get('detail', '')}")
    return 0 if checks["nvidia_driver"]["status"] == "READY" else 1


if __name__ == "__main__":
    sys.exit(main())
