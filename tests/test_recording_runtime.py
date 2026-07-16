import os
import subprocess
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from recording_runtime import calculate_timeout_seconds, run_process_group
import record_from_guide


class RecordingRuntimeTest(unittest.TestCase):
    def test_duration_based_timeout_is_bounded(self):
        settings = {
            "timeout_margin_minutes": 10,
            "minimum_timeout_minutes": 15,
            "maximum_timeout_minutes": 240,
        }
        self.assertEqual(calculate_timeout_seconds(30, settings), 40 * 60)
        self.assertEqual(calculate_timeout_seconds(1, settings), 15 * 60)
        self.assertEqual(calculate_timeout_seconds(9999, settings), 240 * 60)

    def test_test_override(self):
        with mock.patch.dict(os.environ, {"KOERADI_RECORDING_TIMEOUT_SECONDS": "2"}):
            self.assertEqual(calculate_timeout_seconds(30), 2)

    def test_timeout_terminates_process_group(self):
        command = [sys.executable, "-c", "import time; time.sleep(60)"]
        result = run_process_group(command, timeout_seconds=0.1, grace_seconds=0.2)
        returncode, _, _, timed_out, _, elapsed, pid = result
        self.assertEqual(returncode, 124)
        self.assertTrue(timed_out)
        self.assertLess(elapsed, 2)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def _shell_fixture(self, vendor_body):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "scripts").mkdir()
        (root / "config").mkdir()
        (root / "scripts" / "record_test.sh").write_bytes(
            (Path(__file__).parents[1] / "scripts" / "record_test.sh").read_bytes()
        )
        (root / "scripts" / "recording_runtime.py").write_bytes(
            (Path(__file__).parents[1] / "scripts" / "recording_runtime.py").read_bytes()
        )
        (root / "config" / "stations.yaml").write_text(
            "stations:\n  - station_id: TEST\n    station_name: Test Station\n", encoding="utf-8"
        )
        (root / "config" / "settings.yaml").write_text("recording: {}\n", encoding="utf-8")
        vendor = root / "fake_vendor.sh"
        vendor.write_text(vendor_body, encoding="utf-8")
        vendor.chmod(0o755)
        return root, vendor

    def test_shell_success_atomically_renames_partial_file(self):
        root, vendor = self._shell_fixture(
            "#!/bin/bash\nwhile getopts 's:f:d:o:' opt; do [ \"$opt\" = o ] && output=$OPTARG; done\nprintf test > \"$output\"\n"
        )
        env = {**os.environ, "KOERADI_VENDOR_SCRIPT": str(vendor), "KOERADI_RECORDING_TIMEOUT_SECONDS": "2"}
        subprocess.run(["bash", str(root / "scripts/record_test.sh"), "TEST", "202607160100", "1", "sample"], check=True, env=env, capture_output=True)
        final = root / "data/audio/Test Station/2026/07/2026-07-16_sample.m4a"
        partial = root / "data/failed_recordings/Test Station/2026/07/2026-07-16_sample.part.m4a"
        self.assertEqual(final.read_bytes(), b"test")
        self.assertFalse(partial.exists())

    def test_shell_timeout_keeps_partial_out_of_audio_tree(self):
        root, vendor = self._shell_fixture(
            "#!/bin/bash\nwhile getopts 's:f:d:o:' opt; do [ \"$opt\" = o ] && output=$OPTARG; done\nprintf partial > \"$output\"\nsleep 60\n"
        )
        env = {**os.environ, "KOERADI_VENDOR_SCRIPT": str(vendor), "KOERADI_RECORDING_TIMEOUT_SECONDS": "1"}
        result = subprocess.run(["bash", str(root / "scripts/record_test.sh"), "TEST", "202607160100", "1", "sample"], env=env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 124)
        self.assertFalse(any((root / "data/audio").rglob("*.m4a")))
        self.assertTrue(any((root / "data/failed_recordings").rglob("*.part.m4a")))
        self.assertIn("classification=RECORDING_TIMEOUT", (root / "logs/record_test.log").read_text(encoding="utf-8"))

    def test_program_timeout_does_not_block_next_program(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        filtered = root / "filtered/TEST"
        filtered.mkdir(parents=True)
        programs = [
            {"title": "timeout", "start_time": "2020-01-01T01:00:00", "end_time": "2020-01-01T01:01:00", "duration_minutes": 1},
            {"title": "success", "start_time": "2020-01-01T02:00:00", "end_time": "2020-01-01T02:01:00", "duration_minutes": 1},
        ]
        (filtered / "2020-01-01.json").write_text(
            __import__("json").dumps({"matched_programs": programs}), encoding="utf-8"
        )
        results = [
            (124, None, None, True, False, 1.0, 1001),
            (0, None, None, False, False, 0.1, 1002),
        ]
        messages = []
        with mock.patch.object(record_from_guide, "FILTERED_PROGRAMS_DIR", root / "filtered"), \
             mock.patch.object(record_from_guide, "PROJECT_ROOT", root), \
             mock.patch.object(record_from_guide, "load_station_map", return_value={"TEST": "Test"}), \
             mock.patch.object(record_from_guide, "run_process_group", side_effect=results) as runner, \
             mock.patch.object(record_from_guide, "log_message", side_effect=messages.append), \
             mock.patch.object(sys, "argv", ["record_from_guide.py", "--station", "TEST", "--date", "2020-01-01", "--filtered-only"]):
            record_from_guide.main()
        self.assertEqual(runner.call_count, 2)
        self.assertTrue(any("タイムアウト: 1" in message for message in messages))
        self.assertTrue(any("成功: 1" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
