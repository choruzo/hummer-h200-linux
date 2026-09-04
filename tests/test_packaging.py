"""Phase 12: the shipped artefacts must agree with the code.

Cheap checks that catch the mistakes nobody notices until a user installs the
release: a udev rule for the wrong VID/PID, an ExecStart with a metric the
daemon does not know, a version that no longer matches the tarball name.
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest

from support import h200d

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts)) as f:
        return f.read()


class Version(unittest.TestCase):

    def test_version_looks_like_a_release(self):
        self.assertRegex(h200d.__version__, r"^\d+\.\d+\.\d+$")

    def test_make_release_extracts_the_same_version(self):
        # The exact regex packaging/make-release.sh uses to name the tarball.
        found = re.search(r'__version__ = "([^"]+)"', read("h200d.py")).group(1)
        self.assertEqual(found, h200d.__version__)


class UdevRule(unittest.TestCase):

    def setUp(self):
        self.rule = read("packaging", "70-hummer-h200.rules")

    def test_matches_the_vid_pid_the_daemon_looks_for(self):
        vid, pid = "%04x" % h200d.VID, "%04x" % h200d.PID
        self.assertIn('ATTRS{idVendor}=="%s"' % vid, self.rule)
        self.assertIn('ATTRS{idProduct}=="%s"' % pid, self.rule)
        self.assertIn('ATTR{idVendor}=="%s"' % vid, self.rule)

    def test_no_stray_vid_pid_slipped_in(self):
        ids = set(re.findall(r'idVendor\}=="([0-9a-fA-F]{4})"', self.rule))
        self.assertEqual(ids, {"%04x" % h200d.VID})

    def test_hidraw_node_is_not_world_writable(self):
        self.assertIn('MODE="0660"', self.rule)
        self.assertNotIn("0666", self.rule)

    def test_group_matches_the_service_user(self):
        unit = read("packaging", "h200d.service")
        group = re.search(r'GROUP="([^"]+)"', self.rule).group(1)
        self.assertIn("Group=%s" % group, unit)


class SystemdUnit(unittest.TestCase):

    def setUp(self):
        self.unit = read("packaging", "h200d.service")

    def test_execstart_only_uses_metrics_the_daemon_knows(self):
        exec_line = re.search(r"^ExecStart=(.*)$", self.unit, re.M).group(1)
        metrics = re.search(r"--metrics\s+(\S+)", exec_line)
        self.assertIsNotNone(metrics, "ExecStart lost its --metrics")
        for name in metrics.group(1).split(","):
            self.assertIn(name, h200d.METRICS)

    def test_execstart_flags_exist_in_the_cli(self):
        exec_line = re.search(r"^ExecStart=(.*)$", self.unit, re.M).group(1)
        helptext = subprocess.run(
            [os.environ.get("PYTHON", "python3"),
             os.path.join(ROOT, "h200d.py"), "--help"],
            stdout=subprocess.PIPE, check=True).stdout.decode()
        for flag in re.findall(r"(--[a-z-]+)", exec_line):
            self.assertIn(flag, helptext)

    def test_runs_unprivileged_and_restarts(self):
        self.assertIn("User=h200", self.unit)
        self.assertIn("Restart=on-failure", self.unit)
        self.assertNotIn("User=root", self.unit)

    def test_can_reach_the_hidraw_node(self):
        self.assertIn("DeviceAllow=char-hidraw rw", self.unit)

    def test_installed_for_boot(self):
        self.assertIn("WantedBy=multi-user.target", self.unit)


class Scripts(unittest.TestCase):

    @unittest.skipIf(not shutil.which("bash"), "bash not available")
    def test_shell_scripts_parse(self):
        for script in ("install.sh", "packaging/make-release.sh"):
            with self.subTest(script=script):
                subprocess.run(["bash", "-n", os.path.join(ROOT, script)],
                               check=True)

    @unittest.skipIf(not shutil.which("shellcheck"), "shellcheck not installed")
    def test_shellcheck_is_clean(self):
        # CI runs this too; having it here means a broken script fails locally
        # instead of six minutes into a release build.
        subprocess.run(["shellcheck", os.path.join(ROOT, "install.sh"),
                        os.path.join(ROOT, "packaging/make-release.sh")],
                       check=True)

    def test_shipped_files_exist(self):
        for path in ("h200d.py", "install.sh",
                     "packaging/70-hummer-h200.rules",
                     "packaging/h200d.service",
                     "research/PROTOCOL.md", "research/METHOD.md"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, path)), path)

    def test_daemon_is_executable(self):
        self.assertTrue(os.access(os.path.join(ROOT, "h200d.py"), os.X_OK))

    def test_daemon_has_no_third_party_imports(self):
        # The whole point of the project: stdlib only, single file.
        imports = re.findall(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)",
                             read("h200d.py"), re.M)
        allowed = {"argparse", "glob", "os", "re", "select", "struct", "sys",
                   "time"}
        self.assertLessEqual(set(i.split(".")[0] for i in imports), allowed)


class StagedInstall(unittest.TestCase):
    """install.sh DESTDIR mode: the same code path a release runs as root."""

    def setUp(self):
        if not shutil.which("bash"):
            self.skipTest("bash not available")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.join(tmp.name, "root")

    def install(self, *args):
        env = dict(os.environ, DESTDIR=self.root)
        return subprocess.run([os.path.join(ROOT, "install.sh")] + list(args),
                              cwd=ROOT, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=True)

    def test_install_then_uninstall_leaves_nothing_behind(self):
        self.install()
        expected = ["usr/local/bin/h200d",
                    "etc/udev/rules.d/70-hummer-h200.rules",
                    "etc/systemd/system/h200d.service",
                    "usr/local/share/doc/h200d/PROTOCOL.md",
                    "usr/local/share/doc/h200d/METHOD.md"]
        for rel in expected:
            self.assertTrue(os.path.isfile(os.path.join(self.root, rel)), rel)
        self.assertTrue(os.access(
            os.path.join(self.root, "usr/local/bin/h200d"), os.X_OK))

        self.install("--uninstall")
        for rel in expected:
            self.assertFalse(os.path.exists(os.path.join(self.root, rel)), rel)

    def test_staged_install_touches_nothing_on_the_system(self):
        out = self.install().stdout.decode()
        self.assertIn("nothing on this system was touched", out)

    def test_installed_daemon_is_the_same_file(self):
        self.install()
        with open(os.path.join(self.root, "usr/local/bin/h200d")) as f:
            self.assertEqual(read("h200d.py"), f.read())


if __name__ == "__main__":
    unittest.main()
