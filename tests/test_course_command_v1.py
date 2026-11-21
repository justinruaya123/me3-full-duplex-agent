"""Exercise the course command with a disposable upstream CLI."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


class CourseCommandTests(unittest.TestCase):
    def test_combined_benchmark_keeps_running_after_a_failed_scenario(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            shutil.copy2(root / "benchmark.sh", project)
            (project / ".env").write_text("")
            (project / "scripts").mkdir()
            shutil.copy2(root / "scripts/legacy-benchmark.sh", project / "scripts")
            course = project / "scripts/course-benchmark.sh"
            course.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > course-args\nexit 7\n')
            course.chmod(0o755)
            # CI may have neither expect nor an interactive terminal.
            expect = project / "expect"
            expect.write_text('#!/bin/sh\nshift 2\nexec ./scripts/course-benchmark.sh "$@"\n')
            expect.chmod(0o755)
            python = project / "fixture-python"
            python.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> stages\n'
                'case "$*" in *"--acknowledgment mm-hmm"*) exit 1;; esac\n'
            )
            python.chmod(0o755)

            def run_benchmark(*args):
                return subprocess.run(
                    ["bash", "benchmark.sh", "--legacy", *args], cwd=project,
                    env=dict(os.environ, FDBENCH_ASSISTANT_PYTHON=str(python),
                             FDBENCH_DIR=str(project / "class"), ME3_ENV_FILE=".env",
                             PATH=f"{project}:{os.environ['PATH']}"),
                    capture_output=True, text=True, timeout=15,
                )

            run = run_benchmark()
            self.assertNotEqual(run.returncode, 0)
            status, = project.glob(".local/benchmarks/*/status.tsv")
            self.assertIn("course\t7\n", status.read_text())
            self.assertIn("mm-hmm\t1\n", status.read_text())
            self.assertIn("checkpoint\t0\n", status.read_text())
            args = (project / "course-args").read_text().splitlines()
            for flag, value in (("--rounds", "3"), ("--phrases", "10"), ("--runs", "3")):
                self.assertEqual(args[args.index(flag) + 1], value)
            stages = (project / "stages").read_text()
            for label in ("--acknowledgment mm-hmm", "--acknowledgment yeah",
                          "--scenario checkpoint", "me3.tts_probe"):
                self.assertIn(label, stages)

            # Upstream can write results.json and exit zero despite scoring errors.
            course.write_text(
                '#!/bin/sh\nrun="$FDBENCH_DIR/runs/$2/run1"\n'
                'mkdir -p "$run/trials/trial1"\n'
                """echo '{"queue_summary":{"done":1,"total":1}}' > "$run/results.json"\n"""
                """echo '{"score_error":"ASR unavailable"}' > "$run/trials/trial1/timing.json"\n"""
            )
            python.write_text(
                f'#!/bin/sh\nif [ "$1" = "-" ]; then exec "{sys.executable}" "$@"; fi\n'
            )
            run = run_benchmark()
            self.assertNotEqual(run.returncode, 0, "lost a per-recording scorer failure")

            previous, = (project / "class/runs").glob("*/run1")
            (previous / "queue.json").write_text("{}")
            (previous / "session.json").write_text("{}")
            (previous / "trials/trial1/timing.json").write_text("{}")
            course.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > course-args\n')
            run = run_benchmark("--resume", str(previous))
            self.assertEqual(run.returncode, 0, run.stderr)
            args = (project / "course-args").read_text().splitlines()
            self.assertEqual(args[args.index("--resume") + 1], str(previous))

    def test_upstream_receives_role_environment_and_real_reset_hooks(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            bench = base / "class repo"
            python = bench / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$ME3_TTS_BACKEND" "$ME3_FOREGROUND_MODEL" "$@"\n')
            python.chmod(0o755)
            (bench / 'launch_assistant.py').touch()
            env = base / "mac.env"
            env.write_text("ME3_TTS_BACKEND=local\nME3_FOREGROUND_MODEL='selected/id'\n")
            run = subprocess.run(
                ["bash", "scripts/course-benchmark.sh", "--student", "test", "--rounds", "1"],
                env=dict(os.environ, ME3_ENV_FILE=str(env), FDBENCH_DIR=str(bench),
                         FDBENCH_ASSISTANT_PYTHON=sys.executable),
                text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            for arg in ("local", "selected/id", "fdbench", "run", "--assistant-cmd",
                        "--reset-cmd", "--student", "--no-utmos"):
                self.assertIn(arg, run.stdout.splitlines())
            self.assertIn("benchmark_control.py", run.stdout)
