#!/usr/bin/bash
# SPDX-License-Identifier: MIT
# Preview by default. Only the explicit legacy camera allowlist is affected.
set -euo pipefail

legacy_packages=(
  v4l2-relayd libcamera-ipu6-tuning
  intel-ipu6-dkms-git intel-ipu6-dkms intel-ipu6ep-camera-hal-git
  intel-ipu6-camera-hal-git intel-ipu6-camera-bin icamerasrc-git icamerasrc
  intel-ivsc-driver-dkms-git intel-ivsc-firmware
)
# Intentionally keep v4l2loopback, stock libcamera, firmware and PipeWire: the new
# package needs them, and another application may also use them.
root_dir=''

require_root() {
  (( EUID == 0 )) || { printf 'Run with sudo and --apply to perform this cleanup.\n' >&2; return 1; }
}

discover_files() {
  local relative file
  files=()
  for relative in \
    etc/default/v4l2-relayd \
    etc/modprobe.d/v4l2-relayd.conf \
    etc/modules-load.d/v4l2-relayd.conf \
    etc/udev/rules.d/99-udmabuf.rules \
    etc/udev/rules.d/99-ipu6-camera.rules \
    etc/systemd/system/ipu6-camera-ready.service \
    etc/systemd/system/v4l2-relayd.service; do
    file="$root_dir/$relative"
    [[ -e $file || -L $file ]] && files+=("$file")
  done
  local -a candidates=()
  shopt -s nullglob
  candidates+=("$root_dir"/etc/v4l2-relayd.d/*.conf)
  candidates+=("$root_dir"/etc/systemd/system/v4l2-relayd.service.d/*.conf)
  candidates+=("$root_dir"/etc/systemd/system/v4l2-relayd@.service.d/*.conf)
  # Once pacman removes a unit file, systemctl is-enabled reports not-found
  # even if its old wants symlink remains. Back up and retire those explicitly.
  candidates+=("$root_dir"/etc/systemd/system/*.{wants,requires}/v4l2-relayd.service)
  candidates+=("$root_dir"/etc/systemd/system/*.{wants,requires}/v4l2-relayd@*.service)
  candidates+=("$root_dir"/etc/systemd/system/*.{wants,requires}/ipu6-camera-ready.service)
  for relative in 50-disable-libcamera.conf 50-disable-libcamera-monitor.conf 99-libcamera.conf disable-v4l2.conf; do
    candidates+=("$root_dir/etc/wireplumber/wireplumber.conf.d/$relative")
  done
  for file in "${candidates[@]}"; do
    [[ -f $file || -L $file ]] && files+=("$file")
  done
  shopt -u nullglob
}

main() {
  local mode=${1:---dry-run} package file owner backup_dir unit
  [[ $# -le 1 && ( $mode == --dry-run || $mode == --apply ) ]] || {
    printf 'Usage: %s [--dry-run|--apply]\n' "$0" >&2; return 2;
  }
  local -a installed=() files=() units=()
  for package in "${legacy_packages[@]}"; do
    if pacman -Qq "$package" >/dev/null 2>&1; then installed+=("$package"); fi
  done
  discover_files
  printf 'Legacy packages to remove (no recursive dependency removal):\n'
  if ((${#installed[@]})); then printf '  %s\n' "${installed[@]}"; else printf '  none\n'; fi
  printf 'Legacy configuration to back up and retire:\n'
  if ((${#files[@]})); then printf '  %s\n' "${files[@]}"; else printf '  none\n'; fi
  printf 'Keeping the stock kernel, firmware, libcamera, PipeWire, portals and v4l2loopback.\n'
  printf 'User camera overrides under ~/.config are not removed; review them before installing.\n'
  [[ $mode == --apply ]] || { printf '\nPreview only. Apply with: sudo %s --apply\n' "$0"; return 0; }
  require_root
  if ((!${#installed[@]} && !${#files[@]})); then printf 'Nothing to clean up.\n'; return 0; fi

  backup_dir="$root_dir/var/lib/archlinux-ipu-webcam/backups/$(date -u +%Y%m%dT%H%M%SZ)-$$"
  install -d -m700 "$backup_dir"
  printf '%s\n' "${installed[@]}" > "$backup_dir/packages.txt"
  for file in "${files[@]}"; do
    local relative=${file#"$root_dir/"}
    install -d -m700 "$backup_dir/$(dirname "$relative")"
    cp -a -- "$file" "$backup_dir/$relative"
  done
  printf 'Backup: %s\n' "$backup_dir"

  # Remember both installed and loaded units before pacman removes unit files.
  # This also catches running template instances without an enable symlink.
  local -A seen=()
  while read -r unit _; do
    case $unit in
      v4l2-relayd.service|v4l2-relayd@*.service|ipu6-camera-ready.service)
        if [[ ! ${seen[$unit]+present} ]]; then
          units+=("$unit")
          seen[$unit]=1
        fi
        ;;
    esac
  done < <(
    systemctl list-unit-files --type=service --no-legend --no-pager
    systemctl list-units --all --type=service --no-legend --no-pager --plain
  )

  # Let pacman enforce reverse dependencies and ask its normal confirmation.
  # If removal fails, no configuration is deleted. Never use -Rdd or -Rns.
  if ((${#installed[@]})); then pacman -R -- "${installed[@]}"; fi
  for unit in "${units[@]}"; do
    if systemctl is-active --quiet "$unit"; then systemctl stop "$unit"; fi
    if systemctl is-enabled --quiet "$unit"; then systemctl disable "$unit"; fi
  done
  for file in "${files[@]}"; do
    [[ -e $file || -L $file ]] || continue
    if owner=$(pacman -Qqo -- "$file" 2>/dev/null); then
      printf 'Keeping %s (still owned by %s)\n' "$file" "$owner"
    else
      rm -- "$file"
    fi
  done
  systemctl daemon-reload
  printf 'Cleanup complete. Install the new package, then reboot. No modules were unloaded.\n'
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; fi
