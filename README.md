# GPU Healthcheck

A reproducible way to test a used NVIDIA GPU before buying it, currently configured
for the **GeForce RTX 4090 (24 GB)**. It runs established diagnostic tools with fixed
durations and a temperature limit, records NVIDIA telemetry while they run, and turns
the results into a report that keeps "failed" and "not tested" separate.

The kit does not ship third-party binaries. OCCT, 3DMark, gpu-burn and memtest_vulkan
come from their official sources. Physical inspection of the card remains part of the
checklist.

## Checks

| Check | Tool | Linux | Windows |
|---|---|---|---|
| Identity, VBIOS, ~24 GB VRAM | NVIDIA `nvidia-smi` | `doctor.py`, runner preflight | logger preflight |
| PCIe link generation and width | NVIDIA `nvidia-smi` | `doctor.py` (informational) | `nvidia-smi -q` |
| FP32 and Tensor Core compute errors | [gpu-burn](https://github.com/wilicc/gpu-burn) | `run_linux.py` | use OCCT |
| VRAM integrity | [memtest_vulkan](https://github.com/GpuZelenograd/memtest_vulkan) | `run_vram.py` | manual |
| VRAM and 3D stability | [OCCT](https://www.ocbase.com/download) | not available | manual GUI |
| Graphics performance reference | [3DMark Time Spy](https://benchmarks.ul.com/3dmark) | not available | manual GUI |
| Temperature, power, clocks, utilization | NVIDIA `nvidia-smi` | `run_linux.py` | `Monitor-RTX4090.ps1` |
| Driver resets (Xid) | kernel log excerpt | `analyze.py` | Event Viewer, manual |
| Optional CUDA/AI sanity and VRAM patterns | PyTorch | `torch_ai_benchmark.py` | same, if installed |
| 16-pin socket, fans, board, invoice | eyes and photos | required | required |

What the automated checks actually do:

- **gpu-burn** runs SGEMM on the GPU and compares each result with a CPU reference.
  With `-tc` it does the same through cuBLAS to exercise Tensor Cores. A mismatch is a
  computation error, not a thermal observation.
- **memtest_vulkan** writes test data through Vulkan compute, reads it back and reports
  mismatches while the test runs. Its own documentation asks for at least 6 minutes.
- **OCCT** repeats VRAM and 3D workloads with its own error detection. OCCT is
  Windows-only and the personal edition is licensed for non-commercial use.
- **3DMark Time Spy Graphics** is a performance reference. It catches a card that is
  far slower than its class; it reports no errors.

## Thresholds

These are the only fixed numbers in the kit:

| Value | Where | Why |
|---|---|---|
| 23,000 MiB VRAM | identity check | A 4090 reports 24564 MiB. A lower figure means this is not a 4090. |
| 88 °C core stop | `run_linux.py`, monitor script | Below NVIDIA's 90 °C maximum operating temperature for the reference 4090. A stop point, not a target. |
| 360 s VRAM test | `analyze.py` | memtest_vulkan's own minimum is "at least 6 minutes". |
| 90% of requested stage time | `analyze.py` | Allows process startup without accepting a truncated run. |
| 16,000 MiB peak allocated | `analyze.py` | `gpu-burn -m 85%` should reserve about 20 GB on an idle card. Far less means the stage did not load the GPU. |

Core temperature is what `nvidia-smi` exposes. Hotspot and memory-junction sensors are
not available there; use HWiNFO or GPU-Z if they are supported by the card.

## Linux quickstart

1. Power off and unplug. Inspect the 16-pin socket and cable for melting, discoloration,
   corrosion or bent contacts. The reference card needs an 850 W system PSU.
2. `python3 tools/doctor.py --gpu 0` checks the driver, identity, VRAM and PCIe link
   without placing load on the GPU.
3. `bash linux/setup_gpu_burn.sh` clones and builds gpu-burn for Ada (`sm_89`). It needs
   `git`, `make`, a C++ compiler and `nvcc`, and it does not overwrite an existing clone.
4. Run two monitored compute stages:

   ```bash
   python3 linux/run_linux.py --gpu 0 --mode quick   # 2 x 4 min
   python3 linux/run_linux.py --gpu 0 --mode full    # 2 x 15 min
   ```

5. Run the VRAM test with the official Linux binary from memtest_vulkan's releases:

   ```bash
   chmod +x external/memtest_vulkan
   python3 linux/run_vram.py --bin external/memtest_vulkan \
       --out results/TEST_YYYYMMDD_HHMMSS_GPU0 --seconds 900
   ```

   If the tool shows a device menu, use `--vulkan-device N` with the menu number, not
   the `nvidia-smi` index. Check that the log says the RTX 4090 was tested, not llvmpipe.

6. Optional, for AI workloads: install CUDA-enabled PyTorch separately, then

   ```bash
   python3 tools/torch_ai_benchmark.py --gpu 0 --seconds 120 --memory-check \
       --json-out results/TEST_YYYYMMDD_HHMMSS_GPU0/torch_ai.json
   ```

7. Optional: export a time-bounded kernel log and let the report check it for Xid errors.
   This needs elevated privileges on most systems.

   ```bash
   sudo journalctl -k --since '2 hours ago' --no-pager > \
       results/TEST_YYYYMMDD_HHMMSS_GPU0/kernel_gpu.log
   ```

8. Generate the report:

   ```bash
   python3 tools/analyze.py results/TEST_YYYYMMDD_HHMMSS_GPU0
   ```

Details and troubleshooting: [linux/README.md](linux/README.md).

## Windows inspection

Use [windows/README.md](windows/README.md): OCCT VRAM and 3D Adaptive tests, memtest_vulkan,
a Time Spy Graphics score, and `windows/Monitor-RTX4090.ps1` for telemetry. The script warns
at 88 °C but does not stop OCCT; stop OCCT manually.

## Reading the report

`report.md` and `report.json` list every check as `PASS`, `MISSING`, `INCONCLUSIVE` or
`FAIL`, with the evidence behind it. The exit status follows the same order:

| Exit | Verdict | Meaning |
|---|---|---|
| 0 | software checks passed | Every required check produced clean evidence. Physical inspection still required. |
| 1 | incomplete | A check is missing or inconclusive. |
| 2 | red flag | A verified error, wrong device or wrong VRAM capacity. Investigate or reject. |

A missing kernel log or a PyTorch environment error makes the report incomplete, not
failed: they say nothing about the GPU itself. `--require-ai` turns a missing PyTorch
result into an incomplete report for AI-focused purchases.

## Development

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m compileall -q tools linux tests
bash -n linux/setup_gpu_burn.sh
```

GitHub Actions runs the same offline checks on Python 3.10 to 3.13 and parses the
PowerShell script. CI has no GPU; it checks the code and parsers only.

## Sources

- [GeForce RTX 4090 specifications](https://www.nvidia.com/en-us/geforce/graphics-cards/40-series/rtx-4090/): 24 GB, 450 W, 90 °C maximum GPU temperature, 850 W system PSU.
- [nvidia-smi documentation](https://docs.nvidia.com/deploy/nvidia-smi/index.html): query fields, temperature limits, ECC and PCIe information.
- [gpu-burn](https://github.com/wilicc/gpu-burn): CUDA stress test used for compute and Tensor Core checks.
- [memtest_vulkan](https://github.com/GpuZelenograd/memtest_vulkan): Vulkan VRAM test; its README recommends at least 6 minutes.
- [OCCT](https://www.ocbase.com/download): VRAM and 3D tests with error detection (Windows).
- [3DMark](https://benchmarks.ul.com/3dmark): Time Spy Graphics score.
- [PyTorch installation](https://pytorch.org/get-started/locally/): CUDA builds for the optional AI check.

## Safety and privacy

- Do not power a card with a damaged or partially seated 16-pin connector. Use the PSU
  and cables rated for the card, at stock clocks and power limits.
- Reproduce a failure on a known-good PSU and system before rejecting the card.
- Test logs can contain the GPU UUID, serial, driver version, hostname and seller
  details. `results/` and `external/` are git-ignored; inspect logs before sharing them.

See [SECURITY.md](SECURITY.md) and [CONTRIBUTING.md](CONTRIBUTING.md).
