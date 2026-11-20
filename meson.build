project('gimp-raw-heic', 'c', 'cpp',
  version : '1.0.0',
  license : 'GPL-3.0-or-later',
  default_options : ['c_std=c11', 'cpp_std=c++17', 'buildtype=release',
                     'warning_level=2'])

cc = meson.get_compiler('c')

gimp_dep   = dependency('gimp-3.0', version : '>=3.0')
gimpui_dep = dependency('gimpui-3.0', version : '>=3.0')
gegl_dep   = dependency('gegl-0.4')
heif_dep   = dependency('libheif', version : '>=1.17')
lcms_dep   = dependency('lcms2')
gexiv2_dep = dependency('gexiv2')
lensfun_dep = dependency('lensfun')
lensfun_db = lensfun_dep.get_variable(pkgconfig : 'datadir', default_value : '') / 'lensfun' / 'version_1'
cygpath = find_program('cygpath', required : false)
if host_machine.system() == 'windows' and cygpath.found()
  # pkg-config reports an MSYS path (/clang64/...); native code needs C:/...
  lensfun_db = run_command(cygpath, '-m', lensfun_db, check : true).stdout().strip()
endif

# LibRaw is linked statically so the plug-in folder needs no extra DLL;
# its own dependencies (zlib, libjpeg, lcms2, libomp, libc++) ship with GIMP.
libraw_dep = dependency('libraw_r', static : get_option('static_libraw'))
extra_deps = []
if host_machine.system() == 'windows'
  # static LibRaw uses ntohs()/htonl() for byte swapping (no networking)
  extra_deps += cc.find_library('ws2_32')
endif

conf = configuration_data()
conf.set_quoted('PLUGIN_VERSION', meson.project_version())
conf.set_quoted('GETTEXT_PACKAGE', 'gimp-raw-heic')
conf.set_quoted('PLUGIN_NAME', 'gimp-raw-heic')
configure_file(output : 'config.h', configuration : conf)

sources = files(
  'src/plugin.c',
  'src/settings.c',
  'src/raw-develop.c',
  'src/profiles.c',
  'src/image.c',
  'src/raw-load.c',
  'src/raw-dialog.c',
  'src/util.c',
  'src/heif-load.c',
  'src/redevelop.c',
  'src/adjust.c',
  'src/batch.c',
  'src/denoise.c',
  'src/presets.c',
  'src/lens.c',
  'src/export-batch.c',
  'src/camprofile.c',
  'src/xmp.c',
)

link_args = []
if host_machine.system() == 'windows'
  link_args += ['-mwindows', '-static-libgcc']
endif

executable('gimp-raw-heic', sources,
  dependencies : [gimp_dep, gimpui_dep, gegl_dep, heif_dep, lcms_dep,
                  gexiv2_dep, libraw_dep, lensfun_dep] + extra_deps,
  c_args : ['-DLIBRAW_NODLL', '-D_USE_MATH_DEFINES', '-fopenmp', '-Wno-unused-parameter'],
  link_args : link_args,
  # LibRaw is C++: link with the C++ driver
  link_language : 'cpp',
  install : false)

subdir('po')

# Unit tests (no running GIMP needed): meson test -C build
unit_tests = executable('unit-tests',
  files('tests/unit/test_core.c', 'src/settings.c', 'src/denoise.c', 'src/util.c',
        'src/presets.c', 'src/lens.c', 'src/heif-load.c', 'src/profiles.c',
        'src/camprofile.c', 'src/xmp.c'),
  dependencies : [gimp_dep, gimpui_dep, gegl_dep, heif_dep, lcms_dep,
                  gexiv2_dep, libraw_dep, lensfun_dep] + extra_deps,
  c_args : ['-DLIBRAW_NODLL', '-D_USE_MATH_DEFINES', '-fopenmp',
            '-Wno-unused-parameter',
            '-DSAMPLES_DIR="' + meson.current_source_dir() / 'samples' + '"',
            '-DLENSFUN_DB_DIR="' + lensfun_db + '"'],
  include_directories : include_directories('.', 'src'),
  link_language : 'cpp',
  build_by_default : true)
test('unit', unit_tests, timeout : 120)
