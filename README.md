# archlinux-ipu-webcam

Make Intel **IPU6 / IPU7 MIPI webcams** work in V4L2-only applications (Zoom,
Teams, Discord, …) on Arch Linux, using the **modern mainline stack** —
no proprietary Intel HAL.

> [!NOTE]
> This is the spiritual successor to
> [`archlinux-ipu6-webcam`](https://github.com/stefanpartheym/archlinux-ipu6-webcam).
> That project bridges the camera through Intel's proprietary
> `ipu6-camera-hal` + `icamerasrc` stack, which is obsolete now that the IPU6/IPU7
> drivers are upstream. This project keeps only the bridging machinery
> (`v4l2-relayd` + `v4l2loopback`) and feeds it from **libcamera** instead.

## How it works

```
sensor (ov01a10 / ov2740 / hi556 …)
  → IPU6/IPU7 ISYS  (raw Bayer, mainline kernel ≥ 6.10)
  → libcamera       (software ISP: debayer + basic processing)
  → gst libcamerasrc → videoconvert → YUY2
  → v4l2-relayd     (on demand: only runs while an app is using the camera)
  → /dev/videoN     (v4l2loopback, "Intel IPU Camera")
  → Zoom / Teams / Discord / browsers
```

Modern browsers (Firefox, Chromium) can already use the camera directly through
PipeWire + libcamera. The piece that's still missing in 2026 is **V4L2-only apps
like Zoom**, which need a real `/dev/video` capture device — that's what this
provides.

### Why `v4l2-relayd` and not a plain GStreamer service?

`v4l2-relayd` starts the `libcamerasrc` pipeline **on demand** (it watches the
loopback's client-usage events) and stops it when no app is using the camera.
So the sensor stays idle — no constant CPU/software-ISP load, no camera LED
stuck on — until something actually opens the webcam.

## Requirements

- A **mainline kernel ≥ 6.10** (IPU6 ISYS is upstream; IPU7 in newer kernels).
- `libcamera` with a working pipeline for your sensor (`cam -l` lists it).
- **Secure Boot disabled**, or a signed `v4l2loopback` DKMS module (the module
  is unsigned by default).
- An AUR helper (`yay` / `paru`) for `v4l2loopback-dkms`.

## Install

```sh
./install.sh          # build + install + enable the relay
./install.sh -t       # also install libcamera-ipu6 (AUR) for color tuning
```

This installs the dependencies, builds `v4l2-relayd` (configured for
`libcamerasrc`), installs a WirePlumber drop-in (see below), and enables
`v4l2-relayd.service`. Reboot afterwards for a clean module/config load.

## Test

```sh
./test.sh                     # preview the raw libcamera source
v4l2-ctl --list-devices       # should list "Intel IPU Camera"
```

In your app, pick **"Intel IPU Camera"** as the webcam.

To preview the loopback device itself once the relay is running, open it in any
webcam app, or:

```sh
ffplay /dev/videoN            # N = the "Intel IPU Camera" node
```

## Uninstall

```sh
./uninstall.sh        # stop/disable the service, remove v4l2-relayd
./uninstall.sh -a     # also remove v4l2loopback-dkms
```

## The WirePlumber drop-in

The IPU6/IPU7 sensor can only be opened by **one** libcamera client at a time.
The package installs
`/usr/share/wireplumber/wireplumber.conf.d/50-disable-libcamera-monitor.conf`,
which disables WirePlumber's libcamera monitor so the relay gets exclusive
access. Applications transparently use the loopback device instead.

If you'd rather use the camera directly from a libcamera-aware app, override
that drop-in in `/etc/wireplumber/wireplumber.conf.d/`.

## Configuration

Edit `/etc/default/v4l2-relayd` and restart `v4l2-relayd.service`:

| Variable    | Default | Notes |
|-------------|---------|-------|
| `VIDEOSRC`  | `libcamerasrc ! videoconvert ! videoscale ! videorate` | Add `camera-name=...` to `libcamerasrc` if you have multiple cameras. |
| `FORMAT`    | `YUY2`  | Widest app compatibility. `NV12` is lighter but rejected by some apps. |
| `WIDTH`/`HEIGHT` | `1280`/`720` | Lower (e.g. `640`/`480`) if the pipeline fails to start. |
| `FRAMERATE` | `30/1`  | |
| `CARD_LABEL`| `Intel IPU Camera` | Must match the label in `/etc/modprobe.d/v4l2-relayd.conf`. |

## Image quality / color

Out of the box libcamera's software ISP has no color tuning for these sensors,
so the image looks greenish/washed out (it falls back to `uncalibrated.yaml`,
which has no color-correction matrix).

This repo ships **`libcamera-ipu6-tuning`**, which installs a calibrated
`ov01a10.yaml` (CCM + AWB, derived from the factory Intel IPU6 AIQB binary) into
`/usr/share/libcamera/ipa/simple/`. `install.sh` builds it by default — no
libcamera rebuild needed. You can preview the effect before installing: just run
`./test.sh`, which auto-loads the bundled tuning via `LIBCAMERA_IPA_CONFIG_PATH`.

A residual warning, `Failed to create camera sensor helper for ov01a10`, is
harmless for color — it refers to a *compiled* gain/exposure helper, not the
tuning. If you also want that (slightly better auto-exposure), install the full
[`libcamera-ipu6`](https://aur.archlinux.org/packages/libcamera-ipu6) via
`./install.sh -t` (it bundles the sensor helper **and** tuning, and conflicts
with `libcamera-ipu6-tuning`).

## Status

> [!WARNING]
> The `libcamerasrc` ↔ `v4l2-relayd` integration (and the WirePlumber drop-in)
> have been derived from how the daemon links its pipeline, but should be
> verified on real hardware per sensor. If the relay fails to start, run
> `./test.sh` first to confirm libcamera works, then check
> `journalctl -u v4l2-relayd` and adjust `WIDTH`/`HEIGHT`/`FORMAT`.

Tested on:

- Dell XPS 13 (sensor `ov01a10`) — _work in progress_

## License

MIT (this repository's scripts/packaging). `v4l2-relayd` is GPL; built from
[its upstream source](https://code.launchpad.net/v4l2-relayd).
