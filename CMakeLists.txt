cmake_minimum_required(VERSION 3.20)
project(PSHost C)
set(CMAKE_C_STANDARD 11)
find_package(PkgConfig REQUIRED)
pkg_check_modules(GIMP REQUIRED gimp-3.0 gimpui-3.0 gtk+-3.0 json-glib-1.0)
add_executable(pshost src/plugin/main.c src/plugin/config.c src/plugin/scan.c src/plugin/ui.c src/plugin/filter.c src/plugin/registry.c src/plugin/restart.c)
target_include_directories(pshost PRIVATE ${GIMP_INCLUDE_DIRS})
target_link_directories(pshost PRIVATE ${GIMP_LIBRARY_DIRS})
target_link_libraries(pshost PRIVATE pe8bf ${GIMP_LIBRARIES})
target_compile_options(pshost PRIVATE ${GIMP_CFLAGS_OTHER} -Wall)

# --- common static analysis library + dev tool + tests ---
# --- translations: po/*.po -> locale/<lang>/LC_MESSAGES/pshost.mo (gettext), Polish catalog also embedded as a fallback ---
find_program(MSGFMT msgfmt REQUIRED)
set(LOCALE_DIR ${CMAKE_BINARY_DIR}/locale)
set(MO_FILES "")
foreach(L pl en)
  add_custom_command(OUTPUT ${LOCALE_DIR}/${L}/LC_MESSAGES/pshost.mo
    COMMAND ${CMAKE_COMMAND} -E make_directory ${LOCALE_DIR}/${L}/LC_MESSAGES
    COMMAND ${MSGFMT} -c -o ${LOCALE_DIR}/${L}/LC_MESSAGES/pshost.mo ${CMAKE_SOURCE_DIR}/po/${L}.po
    DEPENDS ${CMAKE_SOURCE_DIR}/po/${L}.po)
  list(APPEND MO_FILES ${LOCALE_DIR}/${L}/LC_MESSAGES/pshost.mo)
endforeach()
add_custom_command(OUTPUT ${CMAKE_BINARY_DIR}/i18n_embedded.c
  COMMAND ${CMAKE_COMMAND} -DMO=${LOCALE_DIR}/pl/LC_MESSAGES/pshost.mo -DOUT=${CMAKE_BINARY_DIR}/i18n_embedded.c -P ${CMAKE_SOURCE_DIR}/cmake/embed_mo.cmake
  DEPENDS ${LOCALE_DIR}/pl/LC_MESSAGES/pshost.mo ${CMAKE_SOURCE_DIR}/cmake/embed_mo.cmake)
add_custom_target(locale ALL DEPENDS ${MO_FILES})

add_library(pe8bf STATIC src/common/pe8bf.c src/common/pe8_msg.c src/common/pe8_probe.c src/common/i18n.c ${CMAKE_BINARY_DIR}/i18n_embedded.c)
target_compile_options(pe8bf PRIVATE -Wall -Wextra)
add_executable(pe8bf_dump tests/pe8bf_dump.c)
target_link_libraries(pe8bf_dump PRIVATE pe8bf)
enable_testing()
add_executable(test_pe8bf tests/test_pe8bf.c)
target_link_libraries(test_pe8bf PRIVATE pe8bf)
add_test(NAME pe8bf COMMAND test_pe8bf)

# --- runner (standalone, static) ---
add_executable(pshost_runner src/runner/runner.c)
target_compile_options(pshost_runner PRIVATE -Wall -Wextra)
target_link_options(pshost_runner PRIVATE -municode -static)

# --- synthetic test filters (.8bf) ---
enable_language(RC)
add_library(absent_dep SHARED tests/minifilter/absent_dep.c)
set_target_properties(absent_dep PROPERTIES PREFIX "" RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/stubs LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/stubs ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/stubs)
foreach(VARIANT invert tiled crash hang missingdep pica)
  set(VARIANT ${VARIANT})
  configure_file(tests/minifilter/pipl.json.in ${CMAKE_BINARY_DIR}/mini_${VARIANT}.json)
  configure_file(tests/minifilter/pipl.rc.in ${CMAKE_BINARY_DIR}/mini_${VARIANT}.rc)
  add_library(mini_${VARIANT} SHARED tests/minifilter/minifilter.c ${CMAKE_BINARY_DIR}/mini_${VARIANT}.rc)
  set_target_properties(mini_${VARIANT} PROPERTIES PREFIX "" SUFFIX ".8bf" RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/mini LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/mini)
  target_link_options(mini_${VARIANT} PRIVATE -static)
endforeach()
target_compile_definitions(mini_tiled PRIVATE TILED)
target_compile_definitions(mini_crash PRIVATE CRASH)
target_compile_definitions(mini_hang PRIVATE HANG)
target_compile_definitions(mini_missingdep PRIVATE MISSINGDEP)
target_compile_definitions(mini_pica PRIVATE PICA)
target_link_directories(mini_missingdep PRIVATE ${CMAKE_BINARY_DIR}/stubs)
target_link_libraries(mini_missingdep PRIVATE absent_dep)
add_dependencies(mini_missingdep absent_dep)
add_test(NAME runner COMMAND python -I ${CMAKE_SOURCE_DIR}/tests/test_runner.py ${CMAKE_BINARY_DIR})

add_executable(pshost_check tests/pshost_check.c)
target_link_libraries(pshost_check PRIVATE pe8bf)

# --- headless UI test (no libgimp): window rendered off-screen, scan runs against the real runner ---
add_library(pscore_sa STATIC src/plugin/config.c src/plugin/scan.c src/plugin/ui.c src/plugin/registry.c)
target_compile_definitions(pscore_sa PUBLIC PSHOST_STANDALONE)
target_include_directories(pscore_sa PUBLIC ${GIMP_INCLUDE_DIRS})
target_link_directories(pscore_sa PUBLIC ${GIMP_LIBRARY_DIRS})
target_link_libraries(pscore_sa PUBLIC pe8bf ${GIMP_LIBRARIES})
add_executable(ui_snapshot tests/ui_snapshot.c)
target_link_libraries(ui_snapshot PRIVATE pscore_sa)
