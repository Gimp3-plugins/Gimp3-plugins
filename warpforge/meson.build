# SPDX-License-Identifier: GPL-3.0-or-later
# Installs WarpForge into GIMP's system plug-in directory, e.g. for distro or
# Flatpak extension packaging:
#
#   meson setup build -Dgimp_plugin_dir=/app/lib/gimp/3.0/plug-ins
#   meson install -C build
#
# Without the option the directory is taken from gimp-3.0.pc.

project('warpforge', version: '1.0.0rc1', license: 'GPL-3.0-or-later',
        meson_version: '>=0.60')

plugin_root = get_option('gimp_plugin_dir')
if plugin_root == ''
  gimp_dep = dependency('gimp-3.0')
  plugin_root = gimp_dep.get_variable(pkgconfig: 'gimplibdir') / 'plug-ins'
endif
plugin_dir = plugin_root / 'warpforge'

install_data('packaging/plug-in/warpforge.py', install_dir: plugin_dir,
             install_mode: 'rwxr-xr-x')
install_data('LICENSE', install_dir: plugin_dir)
install_subdir('src/warpforge', install_dir: plugin_dir / 'lib',
               exclude_directories: ['native', '__pycache__'])
install_subdir('data/schemas', install_dir: plugin_dir)
