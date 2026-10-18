#!/usr/bin/env python3
"""Hardware-free checks for the destructive cleanup path and runtime validation."""
import os
import ctypes
import ctypes.util
import json
from pathlib import Path
import shlex
import shutil
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
        self.assertEqual(self.config_result('FRAMING=fit\n').returncode, 0)

    def test_invalid_configuration_rejected_before_starting_capture(self):
        for value in ['DEVICE=/dev/sda', 'WIDTH=1279', 'HEIGHT=0', 'FRAMERATE=999',
                      'WIDTH=01280', 'WAIT_SECONDS=99', 'USE_TUNING=maybe', 'FRAMING=stretch',
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

    def test_builtin_udmabuf_does_not_require_a_loadable_module(self):
        result = subprocess.run(['bash', '-c',
            f'source {shlex.quote(str(HERE / "ipu-webcam"))}; '
            'modprobe() { echo "unexpected modprobe" >&2; return 1; }; '
            'ensure_udmabuf /dev/null'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')

    def test_absent_udmabuf_loads_module_and_propagates_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            device = shlex.quote(str(Path(tmp) / 'absent-udmabuf'))
            for status in [0, 1]:
                with self.subTest(module_exit_status=status):
                    result = subprocess.run(['bash', '-c',
                        f'source {shlex.quote(str(HERE / "ipu-webcam"))}; '
                        f'modprobe() {{ printf "%s" "$*"; return {status}; }}; '
                        f'ensure_udmabuf {device}'], text=True, capture_output=True)
                    self.assertEqual(result.stdout, 'udmabuf')
                    self.assertEqual(result.returncode, status)

    def test_actual_framing_preserves_resolution_and_requested_view(self):
        for framing, active_width in [('crop', 1280), ('fit', 1152)]:
            with self.subTest(framing=framing):
                pipeline = subprocess.check_output(['bash', '-c',
                    f'source {shlex.quote(str(HERE / "ipu-webcam"))}; '
                    f'WIDTH=1280; HEIGHT=720; FRAMING={framing}; framing_pipeline'], text=True)
                # Test real GStreamer negotiation and pixels with a 16:10
                # synthetic image; neither path opens any hardware device.
                command = ['gst-launch-1.0', '-q', 'videotestsrc', 'pattern=white',
                           'num-buffers=1', '!', 'video/x-raw,format=RGB,width=1280,height=800,pixel-aspect-ratio=1/1', '!']
                command += shlex.split(pipeline)
                command += ['!', 'video/x-raw,format=RGB,width=1280,height=720,pixel-aspect-ratio=1/1', '!', 'fdsink', 'fd=1']
                result = subprocess.run(command, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(len(result.stdout), 1280 * 720 * 3)
                row = result.stdout[360 * 1280 * 3:361 * 1280 * 3]
                self.assertEqual(sum(value > 200 for value in row[::3]), active_width)

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
    if not os.path.exists(os.environ['MOCK_REMOVED']):
        print('v4l2-relayd@old.service enabled')
        print('v4l2-relayd@.service enabled')
    print('pipewire.service enabled')
if sys.argv[1] == 'list-units':
    print('v4l2-relayd@running.service loaded active running Old relay')
    print('pipewire.service loaded active running PipeWire')
if sys.argv[1] == 'is-enabled':
    sys.exit(0 if sys.argv[-1] in ['v4l2-relayd@old.service', 'v4l2-relayd@.service'] else 1)
if sys.argv[1] in ['is-active', 'stop'] and sys.argv[-1] == 'v4l2-relayd@.service':
    print('Cannot query or stop a template as a running unit', file=sys.stderr)
    sys.exit(1)
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

    def test_cleanup_does_not_query_or_stop_service_templates(self):
        result, _, _, _, _, calls = self.cleanup_case('--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertNotIn('is-active --quiet v4l2-relayd@.service', calls)
        self.assertNotIn('stop v4l2-relayd@.service', calls)
        self.assertIn('disable v4l2-relayd@.service', calls)
        self.assertIn('stop v4l2-relayd@running.service', calls)

    def test_failed_package_removal_preserves_configuration_and_services(self):
        result, root, unowned, owned, unrelated, calls = self.cleanup_case('--apply', fail_removal=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(all(p.exists() for p in (unowned, owned, unrelated)))
        self.assertTrue((root / 'etc/systemd/system/multi-user.target.wants/v4l2-relayd.service').is_symlink())
        self.assertNotIn('systemctl stop', calls)
        self.assertNotIn('systemctl disable', calls)
        self.assertNotIn('systemctl daemon-reload', calls)


@unittest.skipUnless(shutil.which('spa-json-dump') and ctypes.util.find_library('wireplumber-0.5'),
                     'WirePlumber rule checks require the optional WirePlumber installation')
class WirePlumberTests(unittest.TestCase):
    def setUp(self):
        # Exercise WirePlumber's actual parser and rule matcher without opening
        # a PipeWire connection, changing the session, or touching the camera.
        self.wp = ctypes.CDLL(ctypes.util.find_library('wireplumber-0.5'))
        signatures = {
            'wp_spa_json_new_from_string': ([ctypes.c_char_p], ctypes.c_void_p),
            'wp_spa_json_unref': ([ctypes.c_void_p], None),
            'wp_properties_new_empty': ([], ctypes.c_void_p),
            'wp_properties_set': ([ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p], ctypes.c_int),
            'wp_properties_get': ([ctypes.c_void_p, ctypes.c_char_p], ctypes.c_char_p),
            'wp_properties_unref': ([ctypes.c_void_p], None),
            'wp_json_utils_match_rules_update_properties': ([ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.wp, name)
            function.argtypes = arguments
            function.restype = result
        config = json.loads(subprocess.check_output(
            ['spa-json-dump', str(HERE / '90-archlinux-ipu-webcam.conf')], text=True))
        self.rules = self.wp.wp_spa_json_new_from_string(json.dumps(config['monitor.v4l2.rules']).encode())
        self.addCleanup(self.wp.wp_spa_json_unref, self.rules)

    def apply_rules(self, properties):
        props = self.wp.wp_properties_new_empty()
        try:
            for key, value in properties.items():
                self.wp.wp_properties_set(props, key.encode(), value.encode())
            self.wp.wp_json_utils_match_rules_update_properties(self.rules, props)
            return {key: self.wp.wp_properties_get(props, key.encode())
                    for key in ['device.disabled', 'node.disabled', 'priority.session']}
        finally:
            self.wp.wp_properties_unref(props)

    def test_raw_device_hidden_before_driver_capabilities_exist(self):
        result = self.apply_rules({'device.bus-path': 'pci-0000:00:05.0',
                                   'device.name': 'v4l2_device.pci-0000_00_05.0'})
        self.assertEqual(result['device.disabled'], b'true')

    def test_raw_node_disabled_if_device_filter_is_bypassed(self):
        self.assertEqual(self.apply_rules({'api.v4l2.cap.driver': 'isys'})['node.disabled'], b'true')

    def test_loopback_and_usb_cameras_remain_available(self):
        for properties in [
            {'device.bus-path': 'platform:v4l2loopback-060', 'api.v4l2.cap.driver': 'v4l2 loopback'},
            {'device.bus-path': 'pci-0000:00:14.0-usb-0:5:1.0', 'api.v4l2.cap.driver': 'uvcvideo'},
        ]:
            with self.subTest(properties=properties):
                result = self.apply_rules(properties)
                self.assertIsNone(result['device.disabled'])
                self.assertIsNone(result['node.disabled'])


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
