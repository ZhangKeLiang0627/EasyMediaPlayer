#!/usr/bin/env bash
# =============================================================================
# 在任意 Linux 机器（含 GitHub Actions runner）上准备 T113-S3 交叉编译环境
#
# 背景：eMP 系列各应用的 Makefile 把 SDK 路径写死成了
#           /home/hugokkl/tina-sdk/...
#       而 eMP-toolchain 自带的 gcc wrapper 内部又写死了
#           /home/caiyongheng/tina/prebuilt/gcc/linux-x86/arm/toolchain-sunxi-musl/toolchain/
#       两处绝对路径都无法通过环境变量覆盖。本脚本的做法是：把 eMP-toolchain
#       解压到任意位置，再用符号链接把这两个历史路径"补"出来，
#       从而做到零改动应用仓库即可在干净机器上交叉编译。
#
# 用法:
#   ./scripts/setup-t113-toolchain.sh [SDK目录]
# 环境变量:
#   TOOLCHAIN_REF   eMP-toolchain 的分支/tag，默认 main
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_DIR="${1:-${REPO_ROOT}/build/toolchain}"
TOOLCHAIN_REPO="${TOOLCHAIN_REPO:-https://github.com/ZhangKeLiang0627/eMP-toolchain}"
TOOLCHAIN_REF="${TOOLCHAIN_REF:-main}"

# Makefile 里写死的 SDK 根（历史遗留，来自开发机）
LEGACY_SDK_ROOT="/home/hugokkl/tina-sdk"
LEGACY_TOOLCHAIN_DIR="${LEGACY_SDK_ROOT}/prebuilt/gcc/linux-x86/arm/toolchain-sunxi-musl/toolchain"
LEGACY_STAGING_DIR="${LEGACY_SDK_ROOT}/out/t113-pi/staging_dir/target"
LEGACY_FREETYPE_INC="${LEGACY_SDK_ROOT}/out/t113-pi/compile_dir/target/freetype-2.13.2/include"
# gcc wrapper 内部写死的路径（来自 tina-sdk 原始构建者）
WRAPPER_TOOLCHAIN_DIR="/home/caiyongheng/tina/prebuilt/gcc/linux-x86/arm/toolchain-sunxi-musl/toolchain"

log() { printf '\033[0;36m[toolchain]\033[0m %s\n' "$*"; }
die() { printf '\033[0;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

# ---------------------------------------------------------------- 1. 取工具链
if [ -d "${SDK_DIR}/toolchain" ] && [ -d "${SDK_DIR}/sysroot" ]; then
    log "复用已解压的工具链: ${SDK_DIR}"
else
    log "下载 eMP-toolchain (${TOOLCHAIN_REF}) ..."
    rm -rf "${SDK_DIR}"
    mkdir -p "${SDK_DIR}"
    git clone --depth 1 --branch "${TOOLCHAIN_REF}" \
        "${TOOLCHAIN_REPO}" "${SDK_DIR}/src" 2>&1 | tail -2

    log "解压 toolchain (46M) ..."
    tar xzf "${SDK_DIR}/src/tc_toolchain.tar.gz" -C "${SDK_DIR}"
    log "解压 sysroot (32M) ..."
    tar xzf "${SDK_DIR}/src/tc_sysroot.tar.gz" -C "${SDK_DIR}"
fi

# 部署 eMP-toolchain 自带的规范 CMake 工具链文件到 ${SDK_DIR}/cmake/，
# 供 build-all.sh 的 cmake 分支以 -DCMAKE_TOOLCHAIN_FILE=${T113_SDK}/cmake/...
# 引用（T113_SDK == SDK_DIR，工具链文件内部按 -DT113_SDK 解析路径）。
if [ -d "${SDK_DIR}/src/cmake" ]; then
    log "部署规范 CMake 工具链文件 (cmake/build_for_t113s3.cmake) ..."
    mkdir -p "${SDK_DIR}/cmake"
    cp -a "${SDK_DIR}/src/cmake/." "${SDK_DIR}/cmake/"
fi

[ -d "${SDK_DIR}/toolchain" ] || die "toolchain/ 解压失败"
[ -d "${SDK_DIR}/sysroot" ]   || die "sysroot/ 解压失败"

export T113_SDK="${SDK_DIR}"
export STAGING_DIR="${SDK_DIR}/sysroot"

# ---------------------------------------------------- 2. 建立历史路径兼容层
log "建立历史硬编码路径的兼容层 ..."
${SUDO} mkdir -p "$(dirname "${LEGACY_TOOLCHAIN_DIR}")" \
                 "$(dirname "${LEGACY_STAGING_DIR}")" \
                 "$(dirname "${LEGACY_FREETYPE_INC}")" \
                 "$(dirname "${WRAPPER_TOOLCHAIN_DIR}")"

${SUDO} ln -sfn "${SDK_DIR}/toolchain" "${LEGACY_TOOLCHAIN_DIR}"
${SUDO} ln -sfn "${SDK_DIR}/sysroot"   "${LEGACY_STAGING_DIR}"
${SUDO} ln -sfn "${SDK_DIR}/sysroot/usr/include/freetype2" "${LEGACY_FREETYPE_INC}"
${SUDO} ln -sfn "${SDK_DIR}/toolchain" "${WRAPPER_TOOLCHAIN_DIR}"

# ------------------------------------------------------------- 3. 冒烟验证
log "冒烟验证 ..."
CC_BIN="${SDK_DIR}/toolchain/bin/arm-openwrt-linux-gcc"
[ -x "${CC_BIN}" ] || die "找不到交叉编译器: ${CC_BIN}"

# wrapper 是 shell 脚本，必须走兼容层里的绝对路径才能 exec 到真正的 gcc
if ! "${CC_BIN}" --version >/dev/null 2>&1; then
    die "交叉编译器无法执行，检查 ${WRAPPER_TOOLCHAIN_DIR} 是否指向 ${SDK_DIR}/toolchain"
fi
log "  $(${CC_BIN} --version | head -1)"

# 编一个 hello world，确认 sysroot 头文件与库都就位
TMPDIR_HELLO="$(mktemp -d)"
printf '#include <stdio.h>\nint main(void){printf("ok\\n");return 0;}\n' \
    > "${TMPDIR_HELLO}/hello.c"
if ! "${CC_BIN}" "${TMPDIR_HELLO}/hello.c" -o "${TMPDIR_HELLO}/hello" \
        >/dev/null 2>&1; then
    die "hello world 编译失败，sysroot 可能不完整"
fi
log "  hello world 编译通过（输出为 ARM 可执行文件）"

# 输出给后续步骤
cat <<EOF

$(printf '=%.0s' {1..64})
export T113_SDK="${SDK_DIR}"
export STAGING_DIR="${SDK_DIR}/sysroot"
$(printf '=%.0s' {1..64})
EOF

# GitHub Actions: 写入 $GITHUB_ENV 让后续 step 继承
if [ -n "${GITHUB_ENV:-}" ]; then
    {
        echo "T113_SDK=${SDK_DIR}"
        echo "STAGING_DIR=${SDK_DIR}/sysroot"
    } >> "${GITHUB_ENV}"
fi
