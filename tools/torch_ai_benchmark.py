#!/usr/bin/env python3
"""Optional CUDA PyTorch compute verification and VRAM data-pattern test.

Requires torch with CUDA; this does not install or change the environment.
"""
import argparse
import json
import math
import pathlib
import statistics
import sys
import time
from datetime import datetime, timezone


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gpu", type=int, default=0)
    p.add_argument("--seconds", type=int, default=120, help="Approximate repeated fp16 GEMM run (min 10)")
    p.add_argument("--size", type=int, default=4096, help="Square matrix dimension (1024..8192)")
    p.add_argument("--memory-check", action="store_true", help="Fill/read ~75%% of available VRAM with simple byte patterns")
    p.add_argument("--json-out", type=pathlib.Path, default=None)
    a = p.parse_args()
    if a.seconds < 10 or not 1024 <= a.size <= 8192 or a.gpu < 0:
        p.error("seconds >=10, size 1024..8192, gpu >=0")
    results = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "device_index": a.gpu,
               "requested_test_seconds": a.seconds, "matrix_size": a.size, "checks": {}, "status": "INCOMPLETE"}
    try:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA-enabled torch not available: install an appropriate PyTorch build")
        torch.cuda.set_device(a.gpu)
        device = torch.device(f"cuda:{a.gpu}")
        info = torch.cuda.get_device_properties(a.gpu)
        results["name"] = info.name
        results["vram_bytes"] = info.total_memory
        results["torch_version"] = torch.__version__
        results["cuda_runtime"] = torch.version.cuda
        print(f"Device: {info.name}; {info.total_memory / 2**30:.2f} GiB; torch {torch.__version__}")
        if "RTX 4090" not in info.name or info.total_memory < 23 * 2**30:
            raise RuntimeError("Device is not a 24GB desktop RTX 4090")
        # CPU float32 reference for a smaller half-precision CUDA matmul.
        torch.manual_seed(4090)
        small_a = torch.randn((256, 256), dtype=torch.float32)
        small_b = torch.randn((256, 256), dtype=torch.float32)
        reference = small_a @ small_b
        result = (small_a.half().to(device) @ small_b.half().to(device)).float().cpu()
        diff = (reference - result).abs()
        maxdiff = float(diff.max())
        ok = bool(torch.allclose(reference, result, atol=0.08, rtol=0.02))
        results["checks"]["reference_matmul"] = {"pass": ok, "max_abs_difference": maxdiff,
                                                     "comparison": "FP16 GPU vs FP32 CPU reference; tolerance atol=.08 rtol=.02"}
        print(f"FP16 matmul reference: {'PASS' if ok else 'FAIL'}, max absolute error {maxdiff:.6f}")
        if not ok:
            raise RuntimeError("FP16 matrix multiplication verification failed")
        del small_a, small_b, reference, result, diff
        torch.cuda.empty_cache()
        n = a.size
        ga = torch.randn((n, n), dtype=torch.float16, device=device)
        gb = torch.randn((n, n), dtype=torch.float16, device=device)
        for _ in range(3):
            gc = ga @ gb
        torch.cuda.synchronize()
        del gc
        timing_ms = []
        started = time.monotonic()
        while time.monotonic() - started < a.seconds:
            ev_start, ev_end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            ev_start.record()
            out = ga @ gb
            ev_end.record()
            ev_end.synchronize()
            elapsed = max(0.0001, ev_start.elapsed_time(ev_end))
            timing_ms.append(elapsed)
            if not bool(torch.isfinite(out).all().item()):
                raise RuntimeError("FP16 GEMM produced NaN or Inf")
        throughput = (2 * (n ** 3)) / (statistics.median(timing_ms) / 1000) / 1e12
        results["checks"]["gemm"] = {"pass": True, "iterations": len(timing_ms),
                                        "median_latency_ms": round(statistics.median(timing_ms), 4),
                                        "estimated_fp16_tflops": round(throughput, 2),
                                        "note": "Hardware+software-specific FP16 CUDA matrix multiply; not a standard NVIDIA peak metric"}
        print(f"FP16 GEMM: {len(timing_ms)} iterations, median {statistics.median(timing_ms):.3f} ms, {throughput:.1f} TFLOP/s (estimated)")
        del ga, gb, out
        torch.cuda.empty_cache()
        if a.memory_check:
            free_bytes, _total_bytes = torch.cuda.mem_get_info(a.gpu)
            target = int(free_bytes * .75)
            block_size = 128 * 2**20  # reserve headroom for comparison buffer
            blocks = []
            allocated = 0
            while allocated + block_size <= target:
                blocks.append(torch.empty(block_size, device=device, dtype=torch.uint8))
                allocated += block_size
            if not blocks:
                raise RuntimeError("Insufficient GPU memory for a meaningful VRAM check")
            print(f"Checking {allocated / 2**30:.2f} GiB with {len(blocks)} x 128MiB chunks; leaving headroom")
            errors = 0
            for pattern in [0x00, 0xFF, 0xAA, 0x55, 0xA5]:
                for block in blocks:
                    block.fill_(pattern)
                torch.cuda.synchronize()
                for block in blocks:
                    errors += int(torch.count_nonzero(block != pattern).item())
                print(f"VRAM pattern 0x{pattern:02X}: accumulated mismatches = {errors}")
                if errors:
                    break
            results["checks"]["simple_vram_patterns"] = {"pass": errors == 0, "tested_bytes": allocated,
                                                           "patterns": 5, "mismatches": errors,
                                                           "warning": "Data pattern check is not a substitute for OCCT/memtest_vulkan"}
            del blocks
            torch.cuda.empty_cache()
            if errors:
                raise RuntimeError(f"GPU VRAM pattern test found {errors} byte mismatches")
        results["status"] = "PASS"
    except Exception as exc:
        results["status"] = "FAIL/INCONCLUSIVE"
        results["error"] = f"{type(exc).__name__}: {exc}"
        print(f"ERROR: {results['error']}", file=sys.stderr)
    finally:
        if a.json_out:
            a.json_out.parent.mkdir(parents=True, exist_ok=True)
            a.json_out.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(json.dumps(results, indent=2))
    return 0 if results["status"].startswith("PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
