#!/usr/bin/env python3
"""Hardware-free checks for the destructive cleanup path and runtime validation."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent


class PackageTests(unittest.TestCase):
    def config_result(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'camera.conf'
            config.write_text(text)
            env = dict(os.environ, IPU_WEBCAM_CONFIG=str(config))
            return subprocess.run(
                ['bash', '-c', f'source {shlex.quote(str(HERE / "ipu-webcam"))}; load_config'],
                env=env, text=True, capture_output=True,
            )

    def test_defaults_and_valid_custom_configuration(self):
        self.assertEqual(self.config_result('').returncode, 0)
        self.assertEqual(self.config_result('WIDTH=640\nHEIGHT=480\nFRAMERATE=15\n').returncode, 0)

    def test_invalid_configuration_rejected_before_starting_capture(self):
        for value in ['DEVICE=/dev/sda', 'WIDTH=1279', 'HEIGHT=0', 'FRAMERATE=999',
                      'WIDTH=01280', 'WAIT_SECONDS=99', 'USE_TUNING=maybe',
                      "CARD_LABEL='a camera name longer than thirty one characters'"]:
            with self.subTest(value=value):
                self.assertNotEqual(self.config_result(value + '\n').returncode, 0)

    def test_refuses_non_loopback_device(self):
        result = subprocess.run(['bash', '-c',
            f'source {shlex.quote(str(HERE / "ipu-webcam"))}; '
            'DEVICE=/dev/null; CARD_LABEL=anything; '
            'readlink() { printf /sys/devices/pci0000:00/video4linux/null; }; check_loopback'],
            text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not a loopback', result.stderr)

    def cleanup_case(self, mode, fail_removal=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        root = base / 'root'
        unowned = root / 'etc/udev/rules.d/99-udmabuf.rules'
        owned = root / 'etc/modprobe.d/v4l2-relayd.conf'
        unrelated = root / 'etc/modprobe.d/v4l2loopback.conf'
        for file in (unowned, owned, unrelated):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(f'original {file.name}\n')
        link = root / 'etc/systemd/system/multi-user.target.wants/v4l2-relayd.service'
        link.parent.mkdir(parents=True)
        link.symlink_to('/usr/lib/systemd/system/v4l2-relayd.service')
        binaries = base / 'bin'
        binaries.mkdir()
        log = base / 'calls'
        removed = base / 'removed'
        pacman = binaries / 'pacman'
        pacman.write_text('''#!/usr/bin/python3
import os, sys
with open(os.environ['MOCK_CALLS'], 'a') as f: f.write('pacman ' + ' '.join(sys.argv[1:]) + '\\n')
if sys.argv[1] == '-Qq': sys.exit(0 if sys.argv[2] == 'v4l2-relayd' else 1)
if sys.argv[1] == '-R':
    result = int(os.environ.get('MOCK_REMOVE_FAIL', '0'))
    if not result: open(os.environ['MOCK_REMOVED'], 'w').close()
    sys.exit(result)
if sys.argv[1] == '-Qqo':
    if sys.argv[-1].endswith('/v4l2-relayd.conf'): print('another-package'); sys.exit(0)
    sys.exit(1)
sys.exit(2)
''')
        systemctl = binaries / 'systemctl'
        systemctl.write_text('''#!/usr/bin/python3
import os, sys
with open(os.environ['MOCK_CALLS'], 'a') as f: f.write('systemctl ' + ' '.join(sys.argv[1:]) + '\\n')
if sys.argv[1] == 'list-unit-files':
    if not os.path.exists(os.environ['MOCK_REMOVED']): print('v4l2-relayd@old.service enabled')
    print('pipewire.service enabled')
if sys.argv[1] == 'list-units':
    print('v4l2-relayd@running.service loaded active running Old relay')
    print('pipewire.service loaded active running PipeWire')
if sys.argv[1] == 'is-enabled':
    sys.exit(0 if sys.argv[-1] == 'v4l2-relayd@old.service' else 1)
''')
        pacman.chmod(0o755)
        systemctl.chmod(0o755)
        env = dict(os.environ, PATH=f'{binaries}:{os.environ["PATH"]}',
                   MOCK_CALLS=str(log), MOCK_REMOVED=str(removed),
                   MOCK_REMOVE_FAIL=str(int(fail_removal)))
        # Sourcing allows the test to replace only the filesystem root and root
        # check. No test executes sudo, the host pacman, or the host systemctl.
        command = (f'source {shlex.quote(str(HERE / "cleanup.sh"))}; '
                   f'root_dir={shlex.quote(str(root))}; require_root() {{ :; }}; main {mode}')
        result = subprocess.run(['bash', '-c', command], env=env, text=True, capture_output=True)
        return result, root, unowned, owned, unrelated, log.read_text()

    def test_cleanup_preview_never_writes(self):
        result, root, unowned, owned, unrelated, calls = self.cleanup_case('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(p.exists() for p in (unowned, owned, unrelated)))
        self.assertFalse((root / 'var').exists())
        self.assertTrue((root / 'etc/systemd/system/multi-user.target.wants/v4l2-relayd.service').is_symlink())
        self.assertNotIn('pacman -R', calls)
        self.assertNotIn('systemctl', calls)

    def test_cleanup_backs_up_and_preserves_other_package_files(self):
        result, root, unowned, owned, unrelated, calls = self.cleanup_case('--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(unowned.exists())
        self.assertTrue(owned.exists())
        self.assertTrue(unrelated.exists())
        backups = list((root / 'var/lib/archlinux-ipu-webcam/backups').glob('*/etc/udev/rules.d/99-udmabuf.rules'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), 'original 99-udmabuf.rules\n')
        link_path = 'etc/systemd/system/multi-user.target.wants/v4l2-relayd.service'
        self.assertFalse((root / link_path).is_symlink())
        saved_links = list((root / 'var/lib/archlinux-ipu-webcam/backups').glob('*/' + link_path))
        self.assertEqual(len(saved_links), 1)
        self.assertEqual(os.readlink(saved_links[0]), '/usr/lib/systemd/system/v4l2-relayd.service')
        self.assertIn('pacman -R -- v4l2-relayd', calls)
        self.assertNotIn('stop pipewire', calls)
        self.assertNotIn('disable pipewire', calls)
        self.assertIn('disable v4l2-relayd@old.service', calls)
        self.assertIn('stop v4l2-relayd@running.service', calls)

    def test_failed_package_removal_preserves_configuration_and_services(self):
        result, root, unowned, owned, unrelated, calls = self.cleanup_case('--apply', fail_removal=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(all(p.exists() for p in (unowned, owned, unrelated)))
        self.assertTrue((root / 'etc/systemd/system/multi-user.target.wants/v4l2-relayd.service').is_symlink())
        self.assertNotIn('systemctl stop', calls)
        self.assertNotIn('systemctl disable', calls)
        self.assertNotIn('systemctl daemon-reload', calls)


@unittest.skipUnless(os.environ.get('IPU_WEBCAM_TEST_RELAY'), 'relay binary is tested by makepkg check()')
class RelayTests(unittest.TestCase):
    def setUp(self):
        self.binary = os.environ['IPU_WEBCAM_TEST_RELAY']
        self.env = dict(os.environ, GST_DEBUG='2,V4L2_RELAYD:4', GST_DEBUG_NO_COLOR='1')
        self.output = ('appsrc name=appsrc caps=video/x-raw,format=YUY2,width=640,'
                       'height=480,framerate=30/1,pixel-aspect-ratio=1/1,'
                       'interlace-mode=progressive,colorimetry=bt709 ! fakesink sync=false')

    def test_output_parse_error_exits_nonzero(self):
        result = subprocess.run([self.binary, '-o', 'ipu_webcam_nonexistent_element'],
                                env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn('CRITICAL', result.stderr)

    def test_splash_parse_error_exits_nonzero(self):
        result = subprocess.run([self.binary, '-o', self.output,
                                 '-s', 'ipu_webcam_nonexistent_element'],
                                env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn('CRITICAL', result.stderr)

    def test_idle_relay_stops_cleanly_on_sigterm(self):
        # Synthetic frames go only to fakesink. No camera or loopback is opened.
        with tempfile.TemporaryFile(mode='w+') as log:
            process = subprocess.Popen([self.binary, '-o', self.output,
                                        '-s', 'videotestsrc num-buffers=2 ! videoconvert'],
                                       env=self.env, stdout=subprocess.DEVNULL, stderr=log)
            try:
                deadline = time.monotonic() + 10
                stderr = ''
                while time.monotonic() < deadline and process.poll() is None:
                    log.seek(0)
                    stderr = log.read()
                    if 'Running...' in stderr:
                        break
                    time.sleep(0.02)
                self.assertIn('Running...', stderr, 'Relay did not initialize')
                process.terminate()
                process.wait(timeout=5)
                log.seek(0)
                stderr = log.read()
                self.assertEqual(process.returncode, 0, stderr)
                self.assertNotIn('CRITICAL', stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    unittest.main()
