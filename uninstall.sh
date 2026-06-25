#!/usr/bin/env bash

# Disable services and remove the packages installed by install.sh.

if   [[ -x "$(command -v yay)"  ]]; then PKGMAN="yay  -Rsn --noconfirm"
elif [[ -x "$(command -v paru)" ]]; then PKGMAN="paru -Rsn --noconfirm"
else echo "ERROR: Couldn't find yay or paru."; exit 1
fi

sudo systemctl disable --now v4l2-relayd.service 2>/dev/null

# Remove our relay package. v4l2loopback-dkms is left installed by default
# since other software may rely on it; pass -a to remove it as well.
eval "${PKGMAN} v4l2-relayd"

if [[ "${1:-}" == "-a" ]]; then
  eval "${PKGMAN} v4l2loopback-dkms"
fi

echo "Done. The WirePlumber libcamera monitor will re-enable after the next"
echo "'systemctl --user restart wireplumber' or re-login (the drop-in was"
echo "removed with the v4l2-relayd package)."
