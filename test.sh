#!/usr/bin/env bash
#
# Preview the raw libcamera source directly (bypasses the loopback/relay).
# Useful to confirm the sensor + software ISP work before debugging the relay.
#
# NOTE: this needs exclusive access to the camera. If v4l2-relayd is currently
# streaming (i.e. an app has the loopback open), stop it first:
#     sudo systemctl stop v4l2-relayd.service

REPO="$(cd "$(dirname "$0")" && pwd)"

# If the sensor tuning isn't installed system-wide yet, fall back to the copy
# bundled in this repo so the preview reflects the calibrated colours rather
# than the green/washed-out `uncalibrated.yaml`. libcamera appends
# "simple/<sensor>.yaml" to each LIBCAMERA_IPA_CONFIG_PATH root.
if [ ! -f /usr/share/libcamera/ipa/simple/ov01a10.yaml ] \
   && [ -f "${REPO}/libcamera-ipu6-tuning/ov01a10.yaml" ]; then
  _tuneroot="$(mktemp -d)"
  mkdir -p "${_tuneroot}/simple"
  cp "${REPO}/libcamera-ipu6-tuning/"*.yaml "${_tuneroot}/simple/" 2>/dev/null
  export LIBCAMERA_IPA_CONFIG_PATH="${_tuneroot}"
  trap 'rm -rf "${_tuneroot}"' EXIT
  echo "Using bundled sensor tuning (not yet installed system-wide)."
fi

case "${XDG_SESSION_TYPE}" in
  wayland) SINK=waylandsink ;;
  x11)     SINK=ximagesink ;;
  *)       SINK=autovideosink ;;
esac

echo "Previewing libcamerasrc -> ${SINK} (Ctrl-C to stop)..."
LANG=C gst-launch-1.0 libcamerasrc ! videoconvert ! videoscale ! "${SINK}"
