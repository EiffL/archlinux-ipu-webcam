# Maintainer: Francois Lanusse
pkgname=archlinux-ipu-webcam
pkgver=1.0.0
pkgrel=3
pkgdesc='On-demand OV01A10 webcam for the Dell XPS 9315 using upstream IPU6 and libcamera'
arch=('x86_64')
url='https://github.com/EiffL/archlinux-ipu-webcam'
license=('MIT' 'GPL-2.0-only' 'CC0-1.0')
depends=(
  'bash' 'coreutils' 'util-linux' 'kmod' 'systemd' 'glib2'
  'linux>=7.2.7' 'linux-headers' 'linux-firmware-intel'
  'libcamera>=0.7.2' 'libcamera-ipa' 'libcamera-tools'
  'gstreamer' 'gst-plugin-libcamera' 'gst-plugins-base' 'gst-plugins-good'
  'v4l-utils' 'v4l2loopback-dkms>=0.15.4' 'v4l2loopback-utils'
)
makedepends=('gcc' 'pkgconf')
checkdepends=('python')
optdepends=('wireplumber: exposes the virtual camera to PipeWire applications')
conflicts=('v4l2-relayd')
backup=('etc/archlinux-ipu-webcam.conf')
install=archlinux-ipu-webcam.install
options=('!debug')
_relay_commit=d6ec36aae87e765eddef8308f0f58c7b5be95ad7
source=(
  "v4l2-relayd.c::https://gitlab.com/vicamo/v4l2-relayd/-/raw/${_relay_commit}/src/v4l2-relayd.c"
  "v4l2-relayd.LICENSE::https://gitlab.com/vicamo/v4l2-relayd/-/raw/${_relay_commit}/LICENSE"
  'relay-errors.patch'
  'ipu-webcam'
  'archlinux-ipu-webcam.conf'
  'archlinux-ipu-webcam.service'
  'archlinux-ipu-webcam-prepare.service'
  '90-archlinux-ipu-webcam.conf'
  'ov01a10.yaml'
  'README.md'
  'LICENSE'
  'cleanup.sh'
  'test_package.py'
)
# Regenerate after changing package sources with: updpkgsums
sha256sums=('247e0f68d361c5d59410acf74b09fe88ccbbfe7c8ae1797776a8e5e29c588159'
            '87e230b1712256ea3f1898b40576bdd3e2f3349d13060d3912d8185909edebc6'
            'ed4849708b3a44c0c4d5715a9daa23e2e69130147c4a60b7fff81b0d980fe13b'
            '250a5af68b10bf0344e8d606e6994b42c7a5cf6992edd7e87dd32bf3348e6c5b'
            '5e0607a7b0a3648479e7076a7f85a385f253973f63b3c00e264138a36caf7ef5'
            '6ec73af58a6a77c051bf7779112b13d6c59424d6fab37a3e8b991ee91a423852'
            'c5cb5c45b69937b0f969222c8fcfe73988029ee20cbde4b28a1bf86dd47e5e53'
            'a303dc13475757ca6202f5e2777de38d83c5ff5c9aeb2df4437552498b6e81ee'
            '12a9e510f52e4973804099d4b2f0c2fcb32085fa71e8f2581253633d46b46b55'
            'ae042522cf9a36e4a00c51f5f49f8c4c7505fb6c9d43b820d44116f96547fb2b'
            '9aaf15aa817b77d4f67bcbcc134220c1f231621053d2b2ad42e04df7266b5ed7'
            'd8a7d81adb6f34fa8be3c0f4c5fda24358bf3052a7b52b5bcdd0147b7f427aa1'
            '99ae34a7ba7427cb18669ea875fe4043cf660653170ff3274163af9adaffe9ca')

prepare() {
  # makepkg symlinks individual sources; patch a copy, not the download cache.
  mkdir -p relay-build
  cp v4l2-relayd.c relay-build/v4l2-relayd.c
  patch -d relay-build -Np1 < relay-errors.patch
}

build() {
  # Upstream's daemon is a single translation unit. Do not install its generic
  # units/generator/defaults: this package owns one explicit camera service.
  cc $CPPFLAGS $CFLAGS -DV4L2_RELAYD_VERSION='"0.2.0+ipu-webcam"' \
    relay-build/v4l2-relayd.c -o v4l2-relayd $LDFLAGS \
    $(pkg-config --cflags --libs gio-unix-2.0 gstreamer-app-1.0 gstreamer-video-1.0)
}

check() {
  bash -n ipu-webcam cleanup.sh
  IPU_WEBCAM_TEST_RELAY="$srcdir/v4l2-relayd" python -B test_package.py
  ./v4l2-relayd --version
}

package() {
  install -Dm755 v4l2-relayd "$pkgdir/usr/lib/$pkgname/v4l2-relayd"
  install -Dm755 ipu-webcam "$pkgdir/usr/bin/ipu-webcam"
  install -Dm644 archlinux-ipu-webcam.conf "$pkgdir/etc/archlinux-ipu-webcam.conf"
  install -Dm644 archlinux-ipu-webcam.service "$pkgdir/usr/lib/systemd/system/archlinux-ipu-webcam.service"
  install -Dm644 archlinux-ipu-webcam-prepare.service "$pkgdir/usr/lib/systemd/system/archlinux-ipu-webcam-prepare.service"
  install -Dm644 90-archlinux-ipu-webcam.conf "$pkgdir/usr/share/wireplumber/wireplumber.conf.d/90-archlinux-ipu-webcam.conf"
  install -Dm644 ov01a10.yaml "$pkgdir/usr/share/$pkgname/ipa/simple/ov01a10.yaml"
  install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
  install -Dm755 cleanup.sh "$pkgdir/usr/share/$pkgname/cleanup.sh"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
  install -Dm644 v4l2-relayd.LICENSE "$pkgdir/usr/share/licenses/$pkgname/v4l2-relayd.LICENSE"
}
