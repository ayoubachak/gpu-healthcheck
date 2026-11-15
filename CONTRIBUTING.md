# Contributing

Bug reports, parser fixtures and documentation fixes are welcome, as are checks for
other NVIDIA GPUs.

1. Open an issue with the GPU model, OS, driver version and a **redacted** log excerpt.
2. Add an offline test for any new parsing behaviour. Never commit a real GPU UUID,
   serial, invoice, username or hostname.
3. Run the checks locally:

   ```bash
   python3 -m unittest discover -s tests -p 'test_*.py' -v
   python3 -m compileall -q tools linux tests
   bash -n linux/setup_gpu_burn.sh
   ```

4. Do not vendor binaries from OCCT, 3DMark, NVIDIA, gpu-burn or memtest_vulkan. Link to
   the upstream release instead.
5. Do not add overclocking, voltage changes, firmware flashing, elevated commands, or a
   path that reports a hardware PASS without evidence.

CI runs the parsers and scripts only, never a GPU workload.
