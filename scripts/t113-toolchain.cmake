# =============================================================================
# T113-S3 (Allwinner sun8i, ARM Cortex-A7, musl) 交叉编译工具链文件
#
# 供 eMP-* 应用的 CMake 构建在 x86_64 CI runner（GitHub Actions ubuntu-22.04）
# 上使用。必须配合 scripts/setup-t113-toolchain.sh 建立的「历史路径兼容层」：
#   /home/hugokkl/tina-sdk/.../toolchain  -> $ENV{T113_SDK}/toolchain
#   /home/hugokkl/tina-sdk/.../staging_dir -> $ENV{STAGING_DIR}
# （gcc wrapper 内部写死的 /home/caiyongheng/tina/... 也被同样映射到 toolchain）
#
# 设计要点（与能跑通的 Makefile 严格对齐）：
#   * 不设置 CMAKE_SYSROOT：libc/crt 由 gcc wrapper 自带的 sysroot 提供，
#     若用 --sysroot 覆盖成 tina staging_dir 会找不到 crt1.o / libc。
#   * 显式追加 tina staging 的 -I include 与 -L lib（镜像 Makefile 的写法），
#     让 freetype / tplayer / cdx_base / ncurses 等能被正确解析。
#
# 用法（由 scripts/build-all.sh 的 cmake 分支调用）：
#   cmake -B build -DCMAKE_TOOLCHAIN_FILE=<本文件> -DEMP_CROSS=ON
# =============================================================================

set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR arm)

# ---- 交叉编译器（wrapper 脚本，内部经兼容层 exec 真正的 gcc.bin）-------------
set(TOOLCHAIN_BIN "$ENV{T113_SDK}/toolchain/bin")
set(CMAKE_C_COMPILER   "${TOOLCHAIN_BIN}/arm-openwrt-linux-gcc")
set(CMAKE_CXX_COMPILER "${TOOLCHAIN_BIN}/arm-openwrt-linux-g++")

# ---- tina staging_dir（= 解压得到的 sysroot，经兼容层软链）-------------------
set(STAGING_DIR "$ENV{STAGING_DIR}")

# ---- 镜像 Makefile 写死的 tina staging 包含路径 -------------------------------
# Makefile: -I.../staging_dir/target/usr/include
#           -I.../staging_dir/target/usr/include/allwinner
#           -I.../staging_dir/target/usr/include/allwinner/include
#           -I.../compile_dir/target/freetype-2.13.2/include
# （freetype 路径经兼容层软链到 ${STAGING_DIR}/usr/include/freetype2）
add_compile_options(
    -I"${STAGING_DIR}/usr/include"
    -I"${STAGING_DIR}/usr/include/allwinner"
    -I"${STAGING_DIR}/usr/include/allwinner/include"
    -I"${STAGING_DIR}/usr/include/freetype2"
)

# ---- 镜像 Makefile 的 -L staging lib（让 -lfreetype/-ltplayer 等能链接）------
add_link_options(
    -L"${STAGING_DIR}/lib"
    -L"${STAGING_DIR}/usr/lib"
)

# ---- 让 find_* 只在 sysroot 内查找，避免污染到 runner 本机的 x86_64 库 --------
set(CMAKE_FIND_ROOT_PATH "${STAGING_DIR}")
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
