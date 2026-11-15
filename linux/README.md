# Linux workflow

Requirements: a working NVIDIA driver with `nvidia-smi`, Python 3.10+, `git`, `make`,
a C++ compiler, `nvcc` to build gpu-burn, and a Vulkan loader plus the NVIDIA ICD for
memtest_vulkan.

1. **Before powering on:** photograph the unpowered 16-pin socket and cable. Check for
   melting, discoloration, bent pins, missing screws, corrosion and signs of repair.
   Confirm the PSU (850 W for the reference card) and that the cable is fully seated.
2. `python3 tools/doctor.py --gpu 0` reports driver, identity, VRAM, PCIe link and which
   optional tools are present. It places no load on the GPU.
3. `bash linux/setup_gpu_burn.sh` clones wilicc/gpu-burn into `external/gpu-burn` and
   builds it for Ada with `-gencode=arch=compute_89,code=sm_89`. The script refuses to
   overwrite an existing clone, so review the source if you want to.
4. Run the compute stages. `quick` is 2 x 4 minutes, `full` is 2 x 15 minutes, and the
   first uses FP32 while the second uses `-tc` for cuBLAS Tensor Core work:

   ```bash
   python3 linux/run_linux.py --gpu 0 --mode quick
   ```

   The runner refuses any device that is not an RTX 4090 with at least 23,000 MiB.
   It writes `results/TEST_<timestamp>_GPU0/` containing `preflight.txt` (full
   `nvidia-smi -q`), `telemetry.csv` (one sample every ~2 s), `gpu_burn_fp32.log`,
   `gpu_burn_tensor.log` and a preliminary `run.json`. At 88 °C core temperature it
   terminates the running stage and marks the run inconclusive.

5. Download the **Linux x86-64** archive from the memtest_vulkan
   [releases page](https://github.com/GpuZelenograd/memtest_vulkan/releases), unpack it
   to `external/memtest_vulkan` and make it executable. Then:

   ```bash
   python3 linux/run_vram.py --bin external/memtest_vulkan \
       --out results/TEST_YYYYMMDD_HHMMSS_GPU0 --seconds 900
   ```

   After the requested time the runner sends SIGINT so the tool prints its own summary,
   then presses Enter if it asks for a final keypress. If a device menu appears, pass
   `--vulkan-device N` using the menu number. The log must show the RTX 4090 on the
   `Testing ...` line and no errors on the summary line.

   memtest_vulkan may allocate less than the full 24 GB depending on the driver. Read
   the reported memory size; a 3.5 GB allocation does not verify 24 GB of VRAM. This is
   a limitation of the tool, not something the parser can compensate for.

6. Optional for AI buyers: install CUDA-enabled PyTorch from the official instructions
   and save the result into the same directory:

   ```bash
   python3 tools/torch_ai_benchmark.py --gpu 0 --seconds 120 --memory-check \
       --json-out results/TEST_YYYYMMDD_HHMMSS_GPU0/torch_ai.json
   ```

7. Optional driver-fault check. Export a bounded excerpt, and be aware that it may
   contain machine identifiers:

   ```bash
   sudo journalctl -k --since '2 hours ago' --no-pager > \
       results/TEST_YYYYMMDD_HHMMSS_GPU0/kernel_gpu.log
   ```

   The analyzer looks for `NVRM: Xid` and `fallen off the bus`. A hit is marked
   inconclusive rather than failed: the timestamp must be correlated with the test.

8. Regenerate the report:

   ```bash
   python3 tools/analyze.py results/TEST_YYYYMMDD_HHMMSS_GPU0
   ```

Notes:

- The 88 °C cutoff uses core temperature. Hotspot and memory junction are not reported
  by `nvidia-smi` on consumer cards.
- Do not run OCCT, gpu-burn and memtest_vulkan at the same time. A marginal PSU or a
  shared power budget makes the result ambiguous, and heat from one test changes the
  conditions of the next.
- A crash, black screen or Xid during a stage is a warning, not an automatic verdict.
  Repeat it on a known-good PSU and host before rejecting the card.
