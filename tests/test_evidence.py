"""Synthetic GPU evidence regression tests. No hardware or paid dependencies."""
import csv
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
from analyze import burn_result, examine, vram_evidence, vram_result, telemetry_stats  # noqa E402
from doctor import check_driver  # noqa E402


def make_case(folder, *, temp=73, memory_mib=24564, gpu_name="NVIDIA GeForce RTX 4090"):
    folder.mkdir(parents=True, exist_ok=True)
    stages = []
    for name in ("fp32", "tensor"):
        path = f"gpu_burn_{name}.log"
        (folder / path).write_text("100.0% proc'd errors: 0\nTested 1 GPUs:\nGPU 0: OK\n", encoding="utf-8")
        stages.append({"name": name, "log": path, "exit_code": 0,
                       "duration_actual_seconds": 240, "duration_requested_seconds": 240, "thermal_stop": False})
    (folder / "run.json").write_text(json.dumps({"gpu_index": 0, "gpu_name": gpu_name,
        "memory_total_mib": memory_mib, "core_temp_cutoff_C": 88, "stages": stages,
        "thermal_stop": False, "sensor_errors": []}), encoding="utf-8")
    (folder / "memtest_vulkan.log").write_text(
        "Testing 1: Bus=0x01:00 DevId=0x2684 24GB NVIDIA GeForce RTX 4090\n"
        "123 iteration. Passed  900.0 seconds written: 500GB checked: 900GB\n"
        "memtest_vulkan: no any errors, testing PASSed.\n", encoding="utf-8")
    (folder / "memtest_meta.json").write_text(json.dumps({"elapsed_seconds": 901, "timed_out_or_killed": False}), encoding="utf-8")
    with (folder / "telemetry.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["temp_core_C", "power_W", "memory_used_MiB", "gpu_util_pct"])
        writer.writeheader()
        for _ in range(5):
            writer.writerow({"temp_core_C": temp, "power_W": 400, "memory_used_MiB": 21000, "gpu_util_pct": 98})
    (folder / "kernel_gpu.log").write_text("clean GPU driver snippet\n", encoding="utf-8")


class TestEvidence(unittest.TestCase):
    def with_case(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = pathlib.Path(tmp.name)
        make_case(folder)
        return folder

    def test_clean_evidence_software_pass(self):
        self.assertEqual(examine(self.with_case())["exit_code"], 0)

    def test_failing_memtest_blocks_purchase(self):
        folder = self.with_case()
        (folder / "memtest_vulkan.log").write_text("Error found. Mode NEXT_RE_READ\n")
        self.assertEqual(examine(folder)["exit_code"], 2)

    def test_short_vram_duration_inconclusive(self):
        folder = self.with_case()
        (folder / "memtest_meta.json").write_text('{"elapsed_seconds": 120}')
        self.assertEqual(vram_evidence(folder)[0], "INCONCLUSIVE")

    def test_missing_vram_duration_inconclusive(self):
        folder = self.with_case()
        (folder / "memtest_meta.json").unlink()
        self.assertEqual(vram_evidence(folder)[0], "INCONCLUSIVE")

    def test_selected_cpu_vulkan_does_not_pass(self):
        folder = self.with_case()
        (folder / "memtest_vulkan.log").write_text(
            "1: 24GB NVIDIA GeForce RTX 4090\nTesting 2: 8GB llvmpipe (LLVM)\n"
            "memtest_vulkan: no any errors, testing PASSed.\n")
        self.assertEqual(vram_evidence(folder)[0], "INCONCLUSIVE")

    def test_forced_termination_is_not_pass(self):
        folder = self.with_case()
        (folder / "memtest_meta.json").write_text('{"elapsed_seconds": 901,"timed_out_or_killed":true}')
        self.assertEqual(vram_evidence(folder)[0], "INCONCLUSIVE")

    def test_missing_kernel_log_blocks_strict_software_pass(self):
        folder = self.with_case()
        (folder / "kernel_gpu.log").unlink()
        self.assertEqual(examine(folder)["exit_code"], 1)

    def test_xid_requires_investigation(self):
        folder = self.with_case()
        (folder / "kernel_gpu.log").write_text("NVRM: Xid (PCI:0000:01:00): 79\n")
        self.assertEqual(examine(folder)["checks"]["driver_xid"]["status"], "INCONCLUSIVE")

    def test_compute_faulty_is_red_flag(self):
        folder = self.with_case()
        (folder / "gpu_burn_tensor.log").write_text("GPU 0: FAULTY\n")
        self.assertEqual(examine(folder)["exit_code"], 2)

    def test_compute_nonzero_exit_inconclusive(self):
        folder = self.with_case()
        run = json.loads((folder / "run.json").read_text())
        run["stages"][1]["exit_code"] = 3
        (folder / "run.json").write_text(json.dumps(run))
        self.assertEqual(examine(folder)["exit_code"], 1)

    def test_short_compute_stage_inconclusive(self):
        folder = self.with_case()
        run = json.loads((folder / "run.json").read_text())
        run["stages"][0]["duration_actual_seconds"] = 30
        (folder / "run.json").write_text(json.dumps(run))
        self.assertEqual(examine(folder)["exit_code"], 1)

    def test_wrong_gpu_is_red_flag(self):
        folder = self.with_case()
        run = json.loads((folder / "run.json").read_text())
        run["gpu_name"] = "NVIDIA GeForce RTX 3090"
        (folder / "run.json").write_text(json.dumps(run))
        self.assertEqual(examine(folder)["exit_code"], 2)

    def test_too_little_vram_red_flag(self):
        folder = self.with_case()
        run = json.loads((folder / "run.json").read_text())
        run["memory_total_mib"] = 12288
        (folder / "run.json").write_text(json.dumps(run))
        self.assertEqual(examine(folder)["exit_code"], 2)

    def test_thermal_safety_cutoff_inconclusive(self):
        folder = self.with_case()
        with (folder / "telemetry.csv").open("a") as f:
            f.write("88,450,21000,100\n")
        self.assertEqual(examine(folder)["exit_code"], 1)

    def test_no_sensor_data_inconclusive(self):
        folder = self.with_case()
        (folder / "telemetry.csv").unlink()
        self.assertEqual(examine(folder)["exit_code"], 1)

    def test_missing_ai_optional_unless_required(self):
        folder = self.with_case()
        self.assertEqual(examine(folder)["exit_code"], 0)
        self.assertEqual(examine(folder, require_ai=True)["exit_code"], 1)

    def test_inconclusive_ai_environment_is_not_hardware_fault(self):
        folder = self.with_case()
        (folder / "torch_ai.json").write_text('{"status":"FAIL/INCONCLUSIVE","error":"CUDA unavailable"}')
        self.assertEqual(examine(folder)["exit_code"], 1)

    def test_numerical_ai_error_is_red_flag(self):
        folder = self.with_case()
        (folder / "torch_ai.json").write_text('{"status":"FAIL/INCONCLUSIVE","checks":{"reference_matmul":{"pass":false}}}')
        self.assertEqual(examine(folder)["exit_code"], 2)

    def test_empty_kernel_excerpt_inconclusive(self):
        folder = self.with_case()
        (folder / "kernel_gpu.log").write_text("\n")
        self.assertEqual(examine(folder)["exit_code"], 1)

    def test_too_little_gpu_load_vram_inconclusive(self):
        folder = self.with_case()
        with (folder / "telemetry.csv").open("w") as fp:
            fp.write("temp_core_C,power_W,memory_used_MiB,gpu_util_pct\n")
            fp.write("70,350,2000,99\n" * 4)
        self.assertEqual(examine(folder)["exit_code"], 1)

    def test_good_ai_required_pass(self):
        folder = self.with_case()
        (folder / "torch_ai.json").write_text('{"status":"PASS"}')
        self.assertEqual(examine(folder, require_ai=True)["exit_code"], 0)

    def test_missing_driver_not_ready(self):
        # CI machines don't have to provide any GPU.
        r = check_driver(0)
        self.assertIn(r["status"], ("MISSING", "ERROR", "READY", "WRONG_GPU"))


if __name__ == "__main__":
    unittest.main()
