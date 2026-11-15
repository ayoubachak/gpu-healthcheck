import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_evidence import make_case


class TestCLI(unittest.TestCase):
    def test_cli_exit_codes_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            make_case(d)
            cmd = [sys.executable, str(ROOT / "tools/analyze.py"), str(d)]
            a = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(a.returncode, 0, a.stderr)
            self.assertTrue((d / "report.md").is_file())
            self.assertTrue((d / "report.json").is_file())
            self.assertEqual(json.loads((d / "report.json").read_text())["exit_code"], 0)
            (d / "memtest_vulkan.log").write_text("Error found.\n")
            b = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(b.returncode, 2)
            (d / "memtest_vulkan.log").unlink()
            c = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(c.returncode, 1)

    def test_doctor_json_no_gpu_is_cleanly_reported(self):
        p = subprocess.run([sys.executable, str(ROOT / "tools/doctor.py"), "--json"],
                           capture_output=True, text=True)
        self.assertIn(p.returncode, (0, 1))
        self.assertIn("nvidia_driver", json.loads(p.stdout))


if __name__ == "__main__":
    unittest.main()
