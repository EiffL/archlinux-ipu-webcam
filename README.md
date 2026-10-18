# Dell XPS 9315 webcam on Arch Linux

One package for the **Dell XPS 13 9315, Alder Lake IPU6 (`8086:465d`),
OV01A10 sensor**, using the normal Arch kernel and libcamera. It exposes a
**Dell XPS 9315 Camera** virtual webcam for Firefox, Chromium, Zoom, and other
V4L2/PipeWire applications. It does not install Intel's proprietary HAL or
out-of-tree IPU6/IVSC drivers.

This is a machine-specific profile, not a universal IPU6/IPU7 installer.

## Fresh installation

Use a fully updated Arch installation with the standard `linux` kernel. This
package intentionally depends on `linux` and `linux-headers` together so DKMS
can build its loopback module. An alternative kernel needs a deliberate change
to those dependencies, including the corresponding headers.

```sh
sudo pacman -Syu --needed base-devel git
git clone https://github.com/EiffL/archlinux-ipu-webcam.git
cd archlinux-ipu-webcam
makepkg -si
sudo reboot
```

Build as your normal user. All dependencies come from Arch's official
repositories; no AUR helper is needed. The package builds its own private copy
of `v4l2-relayd` 0.2.0 from a pinned, checksummed upstream source.

Installation enables `archlinux-ipu-webcam.service`. It deliberately leaves
the current desktop session alone; reboot applies the kernel module, service,
and WirePlumber configuration together. After login, select **Dell XPS 9315
Camera** in your application and grant its camera permission.

The module must be permitted to load. If you enforce kernel module signatures,
configure DKMS signing using your existing Secure Boot setup.

## Replace the previous camera setup

Build the package before removing the old integration:

```sh
makepkg -sf                          # resolve dependencies; rebuild any existing artifact
./cleanup.sh                         # preview; changes nothing
sudo ./cleanup.sh --apply            # backs up and removes the listed legacy setup
sudo pacman -U "$(makepkg --packagelist)"
sudo reboot
```

The cleanup script uses an explicit list of old camera packages and config
filenames. It keeps the stock kernel, firmware, libcamera, PipeWire, desktop
portals, and v4l2loopback. It does not recursively remove dependencies, force
package removal, unload modules, delete source checkouts, or restart audio.
Pacman still asks its normal package-removal confirmation.

Backups, including the removed package names, are stored under
`/var/lib/archlinux-ipu-webcam/backups/<timestamp>-<pid>/`. Files still owned by
an installed package are kept. If pacman refuses removal, cleanup stops before
deleting configuration. A failed cleanup can be retried after resolving the
reported dependency; do not bypass it with `pacman -Rdd`.

Review camera-specific overrides in `~/.config/wireplumber/` and user services
such as `camera-bridge.service` yourself. The script does not delete user
configuration or unknown files. If you use a replacement `libcamera-ipu6`
package, return its libcamera packages to the official versions before this
installation. Existing virtual cameras for OBS or other applications are not
removed; choose a free device number in the package configuration if necessary.

## What the package does

```text
OV01A10 -> in-tree IPU6/IVSC drivers -> libcamera software ISP
         -> GStreamer conversion -> on-demand relay -> /dev/video60
         -> V4L2 applications / PipeWire / desktop camera portal
```

* A root preparation unit loads `udmabuf` for the software ISP and
  `v4l2loopback`, then creates one explicitly named
  device at `/dev/video60`, with `exclusive_caps=1`. It refuses to overwrite an
  existing unrelated device and never unloads the module.
* The relay runs under a systemd dynamic user with restricted device access.
  It waits for the **sensor entity**, then checks libcamera discovery and DMA
  buffer access as that user. A media node alone is not a readiness signal.
* `v4l2-relayd` listens for loopback consumer events. It starts physical capture
  only while an application uses the virtual camera and releases the sensor
  afterwards. The idle placeholder consists of black frames, not camera images.
* The camera chooses its native capture size. GStreamer converts/letterboxes it
  to **1280x720 YUY2 at 30 fps**, rather than asking the sensor for an unsupported
  resolution. No images are recorded to disk by the service.
* A small relay patch makes capture/event-subscription failures exit with an
  error so systemd can retry, and releases pipelines on SIGTERM. This helps
  recover userspace after transient failures; it cannot repair a stuck kernel
  driver after suspend.
* A WirePlumber fragment disables its direct libcamera monitor and hides raw
  IPU6 `isys` devices from PipeWire. PipeWire instead consumes the virtual
  camera. USB webcams remain available through V4L2. This global libcamera
  monitor choice is intentional for this single-MIPI-camera laptop.
* An OV01A10 colour profile is kept in a **private data directory** and used
  only by this relay. No stock libcamera files are overwritten.

There is no `libcamera.service`. The only added running daemon is this relay;
the preparation unit is a oneshot. Your desktop provides PipeWire/WirePlumber
and its portal when using that application path. Native V4L2 applications do
not require the desktop services to capture from the loopback.

V4L2 applications that enumerate kernel devices directly may still list the
raw IPU6 endpoints. Select the named virtual camera. Don't run direct
`libcamerasrc`, `cam`, or `qcam` capture at the same time as a relay consumer.

## Check and configure

```sh
ipu-webcam status
ipu-webcam test                       # capture 60 frames; save no images
journalctl -b -u archlinux-ipu-webcam.service
journalctl -b -u archlinux-ipu-webcam-prepare.service
v4l2-ctl --list-devices
```

The camera LED should be off when nothing uses it. Test a second open/close,
then suspend/resume and a cold boot. Merely seeing a device or an active service
is not proof of image capture. `ipu-webcam test` checks delivery, not colour
quality; check the preview in an application too.

Edit `/etc/archlinux-ipu-webcam.conf` for output dimensions, frame rate, device
number, label, or colour tuning. Then restart the relay:

```sh
sudo systemctl restart archlinux-ipu-webcam.service
```

Reboot after changing the device number/label; the package does not remove
existing loopbacks. If you change the label, the optional WirePlumber priority
rule will no longer match, but the camera still works.

The service requires group access to camera devices (`video`), GPU rendering
(`render`), and `/dev/udmabuf` (`kvm`, the current Arch/systemd default). Its
device whitelist does **not** grant access to `/dev/kvm`. Check local udev
overrides if readiness reports a DMA-buffer permission error. No world-writable
device permissions or user membership changes are installed.

## Upstream limitations and maintenance

Linux 7.2.7 includes the fix for the 7.2 IVSC discovery regression. The package
requires at least that version on the standard Arch kernel. Do not resurrect
old IPU6/IVSC DKMS drivers to address a userspace configuration failure.

libcamera 0.7.2 supports this sensor, but has a known **auto-exposure gain-step
bug that can cause flicker**. The colour YAML does not fix that code defect.
Fedora carries a small downstream fix; Arch's 0.7.2-4 package does not. This
package retains the distribution's libcamera ABI and updates instead of
shipping a private fork or silently patching installed libraries. If flicker
occurs, use an official update containing the fix or a reviewed package rebuild
with the linked fix. Disabling automatic exposure is not a general solution.

The colour matrices come from a proposed OV01A10 tuning profile; they are not
a measured calibration of this individual laptop. `USE_TUNING=no` allows a
comparison with the distribution's profile. Image quality and suspend recovery
remain dependent on upstream firmware, kernel, and libcamera.

The installed v4l2loopback 0.15.4 can also log `buffer ... was not queued`
from GStreamer's allocator. Frame delivery and reopening succeeded despite
these messages in the local test. This is a separate upstream loopback queue
issue; this package does not replace its DKMS driver. GStreamer's `io-mode=rw`
is not a workaround: its V4L2 output write path is unimplemented. Keep the
tested `mmap` mode and follow the upstream fix linked below.

Useful primary sources:

* [Kernel IPU6 documentation, including XPS 9315](https://docs.kernel.org/admin-guide/media/ipu6-isys.html)
* [Linux 7.2.7 changelog](https://cdn.kernel.org/pub/linux/kernel/v7.x/ChangeLog-7.2.7)
* [libcamera 0.7.2 release](https://lists.libcamera.org/pipermail/libcamera-devel/2026-July/060247.html)
* [OV01A10 tuning submission](https://patchwork.libcamera.org/cover/26657/)
* [OV01A10 exposure issue and downstream fix discussion](https://patchwork.libcamera.org/patch/28081/)
* [Fedora's targeted exposure fix](https://src.fedoraproject.org/rpms/libcamera/raw/rawhide/f/0002-fix-ov01a10-flickering.patch)
* [v4l2-relayd upstream](https://gitlab.com/vicamo/v4l2-relayd)
* [WirePlumber camera configuration](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/video.html)
* [v4l2loopback output queue fix](https://github.com/v4l2loopback/v4l2loopback/pull/656)

## Validation status

On the target laptop with Linux 7.2.9 and libcamera 0.7.2-4, the package's relay
delivered two successive captures (60 and 30 frames) through the existing,
unused loopback at 1280x720 YUY2. A direct libcamera capture then succeeded
while the relay was idle, verifying sensor release. SIGTERM shut it down
cleanly. No camera images were saved.

The package builds and its automated checks cover invalid configuration,
cleanup preview, backups, preservation of unrelated files/services, failed
package removal, relay pipeline errors, and clean shutdown. Unit syntax was
checked with `systemd-analyze verify`.

The local build used `makepkg --nodeps` because the runtime utility package
`v4l2loopback-utils` was not installed; all build/check dependencies were
already present. This avoided changing the host. Use the normal `makepkg -s`
or `makepkg -si` commands above to resolve dependencies for installation.

The package has **not been installed on this machine yet**. The live test ran
as the logged-in user on the existing loopback, not under the packaged dynamic
user or on its newly created exclusive-caps device. Cold boot, application
previews, image quality, and suspend/resume still require an installation test.
Do not interpret a successful build as proof of those integration checks.

## Development and removal

```sh
python -B test_package.py             # no hardware, root, or package changes
makepkg                              # verifies checksums, builds and runs checks
makepkg --printsrcinfo > .SRCINFO     # refresh metadata after PKGBUILD changes
```

Refresh source checksums with `updpkgsums` (from `pacman-contrib`) after editing
packaged files. Never use `--skipinteg` to ship an updated package.

```sh
sudo pacman -R archlinux-ipu-webcam
sudo reboot
```

Removal stops/disables this service and removes its packaged desktop fragment.
Dependencies are kept; the reboot removes the virtual device and restores
native libcamera discovery. Modified `/etc/archlinux-ipu-webcam.conf` is subject
to pacman's normal `.pacsave` handling.
