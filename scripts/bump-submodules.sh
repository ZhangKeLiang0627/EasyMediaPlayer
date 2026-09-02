#!/usr/bin/env bash
# =============================================================================
# 发布前把 apps.yaml 登记的每个 app 子模块指针拉新到其分支的最新提交
#
# 用法:
#   bash scripts/bump-submodules.sh            # 预览（dry-run）
#   bash scripts/bump-submodules.sh --commit   # 有更新则提交
#
# 说明:
#   * 无需把子模块检出到磁盘 —— emp.py bump 用 git ls-remote 取最新 SHA，
#     再用 update-index --cacheinfo 直接改写 gitlink（mode 160000）。
#   * 该步骤由 build-firmware.yml 在 main 上自动执行；tag 触发的构建本身就
#     按分支最新 main 克隆各 app（build-all.sh），并在 firmware.tar.gz 里
#     内置 VERSIONS.txt 记录每个 app 的来源提交。
# =============================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

python3 scripts/emp.py bump "$@"
