#!/usr/bin/env bash

set -euo pipefail

RED='\033[0;31m'
ORANGE='\033[0;33m'
NC='\033[0m'

# AUR helper command (auto-detected below if left empty).
PKGMAN=()
MAKEPKG=(makepkg -si --noconfirm --needed)

FLAG_FULL_TUNING=false   # -t : install libcamera-ipu6 (AUR, full patched libcamera)
FLAG_REBOOT=false        # -r : reboot after install

SUPPORTED_KERNELS=(linux linux-lts linux-zen linux-hardened)

# Packages from the official repos / AUR, in install order.
# The mainline kernel (>= 6.10) already provides the IPU6/IPU7 ISYS driver, so
# no proprietary Intel HAL/firmware DKMS packages are needed anymore.
REPO_PKGS=(
  libcamera
  libcamera-ipa
  gst-plugin-libcamera
  gst-plugins-base
  gst-plugins-good
  gstreamer
  pipewire-libcamera
  wireplumber
  v4l-utils
)
AUR_PKGS=(
  v4l2loopback-dkms
)
# Local packages (directories containing a PKGBUILD), in build order.
# libcamera-ipu6-tuning fixes the green/washed-out colour without rebuilding
# libcamera. It is skipped when -t installs the full libcamera-ipu6 instead.
LOCAL_PKGS=(
  libcamera-ipu6-tuning
  v4l2-relayd
)

error() { printf "${RED}%s${NC} %s\n" "ERROR:" "${1}"; exit 1; }
warn()  { printf "${ORANGE}%s${NC} %s\n" "WARNING:" "${1}"; }

while getopts ":trh" opt; do
  case $opt in
    t) echo "Will install full libcamera-ipu6 (AUR) instead of the lightweight tuning."; FLAG_FULL_TUNING=true ;;
    r) echo "System will reboot after installation."; FLAG_REBOOT=true ;;
    h)
      echo "Usage: ${0} [options]"
      echo "  -t   Install the full patched libcamera-ipu6 (AUR) — sensor helper +"
      echo "       tuning — instead of the lightweight drop-in tuning package."
      echo "  -r   Reboot after installation."
      echo "  -h   Show this help message."
      exit 0 ;;
    \?) echo "Invalid option -$OPTARG" >&2; exit 1 ;;
  esac
done

# Pick an AUR helper.
if [[ "${#PKGMAN[@]}" -eq 0 ]]; then
  if   [[ -x "$(command -v yay)"  ]]; then PKGMAN=(yay  -S --noconfirm --needed)
  elif [[ -x "$(command -v paru)" ]]; then PKGMAN=(paru -S --noconfirm --needed)
  elif [[ -x "$(command -v pamac)" ]]; then PKGMAN=(pamac install --no-confirm)
  else error "No AUR helper found. Install yay or paru, or set PKGMAN in this script."
  fi
fi

# Kernel headers are required to build the v4l2loopback DKMS module.
kernel_exists=false
for kernel in "${SUPPORTED_KERNELS[@]}"; do
  if pacman -Qq "${kernel}" >/dev/null 2>&1; then
    echo "# Install headers for: ${kernel}"
    "${PKGMAN[@]}" "${kernel}-headers" || error "Failed to install ${kernel}-headers"
    kernel_exists=true
  fi
done
$kernel_exists || error "No supported kernel found (${SUPPORTED_KERNELS[*]})."

# Full libcamera-ipu6 replaces the lightweight tuning package (they conflict).
if $FLAG_FULL_TUNING; then
  AUR_PKGS+=(libcamera-ipu6)
  _filtered=()
  for _p in "${LOCAL_PKGS[@]}"; do
    [[ "$_p" == "libcamera-ipu6-tuning" ]] || _filtered+=("$_p")
  done
  LOCAL_PKGS=("${_filtered[@]}")
fi

echo "# Install repo/AUR packages"
"${PKGMAN[@]}" "${REPO_PKGS[@]}" "${AUR_PKGS[@]}" || error "Failed to install dependencies."

echo "# Build and install local packages"
for pkg in "${LOCAL_PKGS[@]}"; do
  [ -f "${pkg}/PKGBUILD" ] || error "Missing ${pkg}/PKGBUILD"
  pushd "${pkg}" >/dev/null
  "${MAKEPKG[@]}" || error "Failed to build/install: ${pkg}"
  popd >/dev/null
done

echo "# Enable and start v4l2-relayd.service"
sudo systemctl enable --now v4l2-relayd.service || error "Failed to enable v4l2-relayd.service"

echo "# Restart WirePlumber so the libcamera-monitor drop-in takes effect"
systemctl --user restart wireplumber 2>/dev/null \
  || warn "Could not restart WirePlumber automatically; log out/in or run 'systemctl --user restart wireplumber'."

cat <<'EOF'

All done.

  - A camera named "Intel IPU Camera" should now appear in v4l2 apps and browsers.
  - Verify with:   v4l2-ctl --list-devices
  - Quick preview: ./test.sh

A reboot is recommended to ensure the v4l2loopback module and WirePlumber
config are cleanly loaded.
EOF

if $FLAG_REBOOT; then
  echo "# Rebooting in 5 seconds..."; sleep 5; reboot
fi
