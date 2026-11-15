# Windows workflow

For a used RTX 4090, a credible inspection is **OCCT, memtest_vulkan, 3DMark and the
NVIDIA sensor logger**. Download each tool from its official source; avoid repackaged
utilities from download sites.

1. **Before powering on:** inspect the unpowered card and the 16-pin connector and cable.
   Look for melting, discoloration, bent contacts, corrosion, missing screws and signs of
   repair. Confirm the PSU and cabling are rated for the card (850 W for the reference
   4090) and that the connector is fully seated.
2. **OCCT** from <https://www.ocbase.com/download>. The personal edition is licensed for
   non-commercial use. Run the *VRAM* test at 80-90% of free VRAM with error detection for
   20 minutes, and the *3D Adaptive* test with error detection for another 20 minutes.
   Save or photograph the error report from each run. A black screen or driver reset is a
   serious warning; check the PSU and driver before blaming the card.
3. **memtest_vulkan** from
   <https://github.com/GpuZelenograd/memtest_vulkan/releases>. Run the Windows binary for
   at least 15 minutes, stop it with Ctrl+C and wait for the summary line. Save the
   console text or a photo. The tool displays which GPU it is testing.
4. **3DMark Time Spy** from <https://benchmarks.ul.com/3dmark>. Record the **Graphics**
   score, not the combined score, and optionally repeat the run two or three times.
   Compare against results for the same card, driver and power limit; there is no fixed
   pass threshold. The value of this test is spotting a card that is far off its class.
5. **Telemetry** in parallel, from PowerShell in the `windows` folder:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Monitor-RTX4090.ps1 `
       -GpuIndex 0 -DurationMinutes 90
   ```

   Outputs `results/windows_<timestamp>/telemetry.csv`, `preflight.txt` and
   `telemetry_notes.txt`. The script refuses a non-4090 device and warns at 88 °C, but
   it does not stop OCCT. Stop the GUI test yourself and investigate cooling or airflow.

6. Keep a phone video showing the test windows, the GPU identity and the final results.
   Photograph the connector and invoice separately, and redact personal details before
   sharing.

GPU-Z (<https://www.techpowerup.com/gpuz/>) is a useful second opinion on identity, VBIOS
and sensors. HWiNFO can show hotspot or memory-junction temperatures that `nvidia-smi`
does not expose.

A failed test should be repeated at stock settings on a known-good PSU before rejecting
the card. See the root [README](../README.md) for the report and buy/no-buy criteria.
