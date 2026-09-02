#!/usr/bin/env bash
# =============================================================================
# 交叉编译全部启用的 eMP 应用，并打包成 firmware.tar.gz
#
# 用法:
#   ./scripts/build-all.sh
# 环境变量:
#   TOOLCHAIN_REF  eMP-toolchain 分支，默认 main
#   JOBS           并行编译数，默认 nproc
# 产物:
#   build/firmware.tar.gz   内含 firmware/ （媒体资源来自仓库，二进制为本次编译结果）
# =============================================================================
# 注意：不要用 set -e。单个 app 编译失败应当继续编译其余 app 并照常打包，
# 由末尾的 BUILT/FAILED 汇总决定是否成功，而不是一失败就中断整条流水线。
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

BUILD_DIR="${REPO_ROOT}/build"
SDK_DIR="${BUILD_DIR}/toolchain"
APPS_DIR="${BUILD_DIR}/apps"
DIST_DIR="${BUILD_DIR}/dist"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 4)}"

log()  { printf '\033[0;36m[build]\033[0m %s\n' "$*"; }
fail() { printf '\033[0;31m[FAIL]\033[0m %s\n' "$*" >&2; }

mkdir -p "${APPS_DIR}" "${DIST_DIR}"

# ------------------------------------------------------------ 1. 准备工具链
log "准备交叉编译工具链 ..."
bash "${REPO_ROOT}/scripts/setup-t113-toolchain.sh" "${SDK_DIR}"
export T113_SDK="${SDK_DIR}"
export STAGING_DIR="${SDK_DIR}/sysroot"

# --------------------------------------------- 2. 以仓库里的资源为基础目录
# firmware/ 里的字体/音视频/配置由 Git 跟踪，二进制由本次编译覆盖
rm -rf "${DIST_DIR}/firmware"
cp -a "${REPO_ROOT}/firmware" "${DIST_DIR}/firmware"
if [ -d "${REPO_ROOT}/image" ]; then
    rm -rf "${DIST_DIR}/image"
    cp -a "${REPO_ROOT}/image" "${DIST_DIR}/image"
fi

# ------------------------------------------------------------- 3. 逐个编译
BUILT=()
FAILED=()

while IFS=$'\t' read -r name repo branch binary build path; do
    [ -z "${name:-}" ] && continue
    log "──────── ${name} ────────"

    src="${APPS_DIR}/${name}"
    rm -rf "${src}"
    if ! git clone --depth 1 --branch "${branch}" \
            "https://github.com/${repo}.git" "${src}" 2>&1 | tail -1; then
        fail "${name}: 克隆失败"
        FAILED+=("${name}")
        continue
    fi
    # 个别 app（如 eMP-gba）内部还嵌了 LVGL 等子模块，depth-1 不会自动拉取
    if [ -f "${src}/.gitmodules" ]; then
        git -C "${src}" submodule update --init --recursive 2>&1 | tail -1 \
            || fail "${name}: 子模块拉取失败"
    fi

    (
        cd "${src}"
        case "${build}" in
        make)
            # 不走 build.sh：它把 STAGING_DIR 硬编码成了开发机路径
            make CROSS=1 -j"${JOBS}"
            ;;
        cmake)
            # 用 eMP-toolchain 自带的规范工具链文件交叉编译（由
            # setup-t113-toolchain.sh 部署到 ${T113_SDK}/cmake/）。该文件把
            # CMAKE_HOST_SYSTEM_PROCESSOR 置为 arm，app 的 CMakeLists 会因此
            # 自动落到 sunxifb 交叉分支 —— 无需改动任何 app 文件。
            cmake -B build \
                -DCMAKE_TOOLCHAIN_FILE="${T113_SDK}/cmake/build_for_t113s3.cmake" \
                -DT113_SDK="${T113_SDK}"
            cmake --build build -j"${JOBS}"
            mv "build/${binary}" "./${binary}"
            ;;
        *)
            fail "${name}: 未知构建方式 ${build}"
            exit 1
            ;;
        esac
    )
    if [ $? -ne 0 ]; then
        fail "${name}: 编译失败"
        FAILED+=("${name}")
        continue
    fi

    if [ ! -f "${src}/${binary}" ]; then
        fail "${name}: 未找到产物 ${binary}"
        FAILED+=("${name}")
        continue
    fi

    cp "${src}/${binary}" "${DIST_DIR}/firmware/${binary}"
    chmod +x "${DIST_DIR}/firmware/${binary}"
    BUILT+=("${binary}")
    log "  ✓ ${binary} ($(du -h "${src}/${binary}" | cut -f1))"

done < <(python3 "${REPO_ROOT}/scripts/emp.py" list)

# ---------------------------------------------------------------- 4. 汇总
echo
log "编译完成：成功 ${#BUILT[@]} 个，失败 ${#FAILED[@]} 个"
if [ ${#BUILT[@]} -gt 0 ]; then
    printf '  %s\n' "${BUILT[@]}"
fi
if [ ${#FAILED[@]} -gt 0 ]; then
    printf '\033[0;33m[warn]\033[0m 以下应用失败，未打进固件：%s\n' "${FAILED[*]}"
fi
[ ${#BUILT[@]} -eq 0 ] && { echo "没有任何应用编译成功"; exit 1; }

# ---------------------------------------------------------------- 5. 打包
TARBALL="${BUILD_DIR}/firmware.tar.gz"
rm -f "${TARBALL}"
tar czf "${TARBALL}" -C "${DIST_DIR}" firmware $([ -d "${DIST_DIR}/image" ] && echo image)

log "产物: ${TARBALL}  ($(du -h "${TARBALL}" | cut -f1))"
tar tzf "${TARBALL}" | sed 's/^/    /' | head -20
echo "    ... ($(tar tzf "${TARBALL}" | wc -l) 项)"

if [ -n "${GITHUB_ENV:-}" ]; then
    echo "FIRMWARE_TARBALL=${TARBALL}" >> "${GITHUB_ENV}"
fi
