#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eMP 应用清单工具。

子命令:
  list              输出启用的应用，每行: name<TAB>repo<TAB>branch<TAB>binary<TAB>build<TAB>path
  discover          扫描 GitHub 上带 emp-app topic（或 eMP-* 命名）的仓库，
                    列出尚未登记进 apps.yaml 的候选
  sync-submodules   依据 apps.yaml 增删子模块（缺失的自动 git submodule add）
  bump              把每个 app 子模块的 gitlink 拉新到其分支最新提交
                    （发布前调用；--commit 提交，--dry-run 只预览）
  check             校验 .gitmodules 与 apps.yaml 是否一致

依赖: 仅标准库（PyYAML 可用时优先使用，否则用内置简易解析器）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "scripts" / "apps.yaml"
OWNER = "ZhangKeLiang0627"
DISCOVER_TOPIC = "emp-app"


# --------------------------------------------------------------------------
# 清单解析
# --------------------------------------------------------------------------
def _parse_lite(text: str) -> list[dict]:
    """解析 apps.yaml 的受限子集：顶层 apps: 列表 + exclude: 列表。"""
    apps: list[dict] = []
    exclude: list[str] = []
    section = None
    current: dict | None = None

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if indent == 0:
            if stripped.startswith("apps:"):
                section, current = "apps", None
            elif stripped.startswith("exclude:"):
                section, current = "exclude", None
            else:
                section = None
            continue

        if section == "apps":
            if stripped.startswith("- "):
                current = {}
                apps.append(current)
                stripped = stripped[2:].strip()
            if current is None:
                continue
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                current[k.strip()] = _coerce(v.strip())
        elif section == "exclude" and stripped.startswith("- "):
            exclude.append(stripped[2:].strip())

    return apps, exclude


def _coerce(v: str):
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    return v.strip("\"'")


def load_manifest() -> tuple[list[dict], list[str]]:
    text = MANIFEST.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
        return data.get("apps") or [], data.get("exclude") or []
    except ImportError:
        return _parse_lite(text)


def enabled_apps() -> list[dict]:
    apps, _ = load_manifest()
    out = []
    for a in apps:
        if not a.get("enabled"):
            continue
        a.setdefault("path", a["name"])
        a.setdefault("build", "make")
        a.setdefault("branch", "main")
        out.append(a)
    return out


def all_apps() -> list[dict]:
    apps, _ = load_manifest()
    for a in apps:
        a.setdefault("path", a["name"])
        a.setdefault("build", "make")
        a.setdefault("branch", "main")
    return apps


# --------------------------------------------------------------------------
# GitHub
# --------------------------------------------------------------------------
def gh(path: str, token: str | None = None) -> dict | list:
    url = path if path.startswith("http") else f"https://api.github.com/{path}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "emp-manifest-tool",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    })
    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    opener = (urllib.request.build_opener(urllib.request.ProxyHandler(
        {"http": proxy, "https": proxy})) if proxy
        else urllib.request.build_opener())
    with opener.open(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def cmd_list(_args) -> int:
    for a in enabled_apps():
        print("\t".join(str(a[k]) for k in
                        ("name", "repo", "branch", "binary", "build", "path")))
    return 0


def cmd_discover(args) -> int:
    token = args.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("EMP_GH_TOKEN")
    _, exclude = load_manifest()
    known = {a["repo"].split("/")[-1] for a in all_apps()}
    known |= set(exclude)

    found: dict[str, dict] = {}

    # 首选：topic 标记（显式、无误判）
    if token:
        try:
            res = gh(f"search/repositories?q=user:{OWNER}+topic:{DISCOVER_TOPIC}"
                     f"&per_page=100", token)
            for r in res.get("items", []):
                found[r["name"]] = r
            source = f"topic:{DISCOVER_TOPIC}"
        except urllib.error.HTTPError as e:
            print(f"[warn] topic 检索失败（{e}），回退到命名约定", file=sys.stderr)
            source = "命名约定 eMP-*"
    else:
        source = "命名约定 eMP-*（未提供 token，无法用 topic 检索）"

    # 回退/补充：命名约定
    if not found:
        try:
            for r in gh(f"users/{OWNER}/repos?per_page=100", token):
                if r["name"].startswith("eMP-"):
                    found[r["name"]] = r
        except urllib.error.HTTPError as e:
            print(f"[error] 仓库列表获取失败: {e}", file=sys.stderr)
            return 1

    new = sorted(n for n in found if n not in known and n != "eMP-toolchain")

    if args.json:
        print(json.dumps([{
            "name": n,
            "url": found[n]["html_url"],
            "language": found[n].get("language"),
            "size_mb": round(found[n].get("size", 0) / 1024, 1),
            "default_branch": found[n].get("default_branch", "main"),
        } for n in new], ensure_ascii=False, indent=2))
        return 0

    print(f"发现来源: {source}")
    print(f"账号下 eMP-* 仓库: {len(found)} 个，已登记/排除: {len(known)} 个")
    print()
    if not new:
        print("没有新应用，一切都是最新的。")
        return 0

    print(f"=== 发现 {len(new)} 个未登记候选 ===")
    for n in new:
        r = found[n]
        print(f"  {n:24s} {str(r.get('language') or '-'):10s} "
              f"{r.get('size', 0) / 1024:7.1f} MB  {r['html_url']}")
    print()
    print("把它们加进 scripts/apps.yaml 后运行：")
    print("    python3 scripts/emp.py sync-submodules")
    return 0


def cmd_sync(args) -> int:
    for a in all_apps():
        path = ROOT / a["path"]
        url = f"https://github.com/{a['repo']}.git"
        if path.exists() and (path / ".git").exists():
            print(f"[skip] {a['path']} 已存在")
            continue
        if args.dry_run:
            print(f"[would add] {a['path']} <- {url}")
            continue
        print(f"[add] {a['path']} <- {url}")
        base = ["git", "submodule", "add"]
        cmd = base + ["--branch", a["branch"], url, a["path"]]
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            # 常见于上次运行被中断，.git/modules/<path> 已存在：
            # 复用本地 git 目录而不是重新克隆
            if "is found locally" in (r.stderr or ""):
                print("      本地已有 git 目录，改用 --force 复用")
                subprocess.run(base + ["--force", "--branch", a["branch"],
                                       url, a["path"]], cwd=ROOT, check=True)
            else:
                print(r.stderr, file=sys.stderr)
                raise SystemExit(1)
    return 0


def cmd_check(_args) -> int:
    gitmodules = ROOT / ".gitmodules"
    if not gitmodules.exists():
        print("[error] 缺少 .gitmodules")
        return 1
    present = set()
    for line in gitmodules.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("path = "):
            present.add(line.split("=", 1)[1].strip())

    wanted = {a["path"] for a in all_apps()}
    missing = wanted - present
    extra = present - wanted
    ok = True
    if missing:
        ok = False
        print("=== apps.yaml 里有、但 .gitmodules 缺失 ===")
        for m in sorted(missing):
            print(f"  - {m}")
    if extra:
        print("=== .gitmodules 里有、但 apps.yaml 未登记 ===")
        for e in sorted(extra):
            print(f"  - {e}")
    if ok:
        print("OK: .gitmodules 与 apps.yaml 一致")
    return 0 if ok else 1


def ls_remote_head(repo: str, branch: str) -> str:
    """查某仓库分支的最新提交 SHA（无需 token）。"""
    url = f"https://github.com/{repo}.git"
    r = subprocess.run(["git", "ls-remote", url, f"refs/heads/{branch}"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f"[warn] ls-remote {repo}@{branch} 失败: "
              f"{(r.stderr or '').strip()}", file=sys.stderr)
        return ""
    return (r.stdout.splitlines() or [""])[0].split("\t")[0]


def cmd_bump(args) -> int:
    """把 apps.yaml 里每个 app 子模块的 gitlink 更新到其分支最新提交。

    不需要子模块检出：直接 git ls-remote 取最新 SHA，再 update-index 覆盖
    gitlink（mode 160000）即可，仓库体积零增长。
    """
    changed: list[tuple[str, str, str, str, str]] = []
    checked = 0
    for a in all_apps():
        path, repo, branch = a["path"], a["repo"], a.get("branch", "main")
        r = subprocess.run(["git", "ls-files", "-s", "--", path], cwd=ROOT,
                           capture_output=True, text=True)
        cur = ""
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[0] == "160000":
                cur = parts[1]
                break
        if not cur:
            print(f"[skip] {path}: 未登记为 gitlink（先跑 sync-submodules）")
            continue
        checked += 1
        latest = ls_remote_head(repo, branch)
        if not latest:
            continue
        if latest == cur:
            print(f"[ok]   {path:26s} 已是最新 {latest[:12]}")
            continue
        print(f"[bump] {path:26s} {cur[:12]} -> {latest[:12]}  ({repo}@{branch})")
        if not args.dry_run:
            subprocess.run(["git", "update-index", "--cacheinfo",
                            f"160000,{latest},{path}"], cwd=ROOT, check=True)
        changed.append((path, cur, latest, repo, branch))

    print(f"\n检查 {checked} 个子模块："
          f"{'全部最新，无需更新' if not changed else f'{len(changed)} 个需要拉新'}")
    if not changed:
        return 0
    if args.dry_run:
        print("(dry-run：仅预览，未改动索引)")
        return 0
    if args.commit:
        body = "\n".join(f"- {p}: {c[:12]} -> {l[:12]} ({r}@{b})"
                         for p, c, l, r, b in changed)
        subprocess.run(["git", "commit", "-m",
                        "chore: 发布前把子模块拉新到各自最新 main\n\n" + body],
                       cwd=ROOT, check=True)
        print("已提交子模块更新")
    else:
        print("已更新索引（未提交）。加 --commit 提交。")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="输出启用应用").set_defaults(func=cmd_list)

    d = sub.add_parser("discover", help="发现未登记的新应用")
    d.add_argument("--token", help="GitHub 令牌（也可用 GITHUB_TOKEN 环境变量）")
    d.add_argument("--json", action="store_true", help="以 JSON 输出，供自动化消费")
    d.set_defaults(func=cmd_discover)

    s = sub.add_parser("sync-submodules", help="按清单增删子模块")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_sync)

    b = sub.add_parser("bump", help="把各 app 子模块指针拉新到分支最新提交")
    b.add_argument("--dry-run", action="store_true", help="只打印不修改")
    b.add_argument("--commit", action="store_true", help="有更新时提交")
    b.set_defaults(func=cmd_bump)

    sub.add_parser("check", help="校验 .gitmodules 一致性").set_defaults(func=cmd_check)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
