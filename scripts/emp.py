#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eMP 应用清单工具。

子命令:
  list              输出启用的应用，每行: name<TAB>repo<TAB>branch<TAB>binary<TAB>build<TAB>path
  discover          扫描 GitHub 上带 emp-app topic（或 eMP-* 命名）的仓库，
                    列出尚未登记进 apps.yaml 的候选
  sync-submodules   依据 apps.yaml 补齐子模块（只 add 未登记的；已登记但
                    未检出的默认跳过，加 --init 才检出）
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
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "scripts" / "apps.yaml"
OWNER = "ZhangKeLiang0627"
DISCOVER_TOPIC = "emp-app"


def _warn(msg: str) -> None:
    """本地打印 [warn]；CI 里输出成 GitHub 注解，醒目但不改变退出码。"""
    print(f"::warning::{msg}" if os.environ.get("GITHUB_ACTIONS") else f"[warn] {msg}")


def _git(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """在仓库根目录跑 git 子命令，带交互禁用与超时。

    GIT_TERMINAL_PROMPT=0 很关键：遇到不存在的仓库或私有仓库时，git 会停在
    "Username for 'https://github.com':" 处等输入。本地凭据助手可能弹窗、
    无人值守的 CI 上就是一直挂到超时；关掉交互后它会立刻 fatal 退出，
    交给上层容错逻辑跳过即可。
    """
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"}
    try:
        # 同时清掉 credential.helper：Windows 下的 manager 会弹 GUI 窗口，
        # GIT_TERMINAL_PROMPT 管不到它，一样会挂住
        return subprocess.run(["git", "-c", "credential.helper=", *args],
                              cwd=ROOT, capture_output=True,
                              text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            ["git", *args], 124, "",
            f"超时（{timeout}s）：git {' '.join(args)}")


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
def gh(path: str, token: str | None = None, retries: int = 2) -> dict | list:
    """GET GitHub API。5xx / 网络抖动 / 超时自动重试，4xx 直接抛。"""
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

    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with opener.open(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            # 4xx 是确定性错误（无权限、参数错），重试没有意义
            if e.code < 500 and e.code != 429:
                raise
        except Exception as e:  # URLError / 超时 / 连接被重置
            last = e
        if attempt < retries:
            time.sleep(2 * (attempt + 1))
    assert last is not None
    raise last


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
        except Exception as e:  # HTTPError / URLError / 超时，一律降级到命名约定
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
        except Exception as e:
            print(f"[error] 仓库列表获取失败: {e}", file=sys.stderr)
            return 1

    new = sorted(n for n in found if n not in known and n != "eMP-toolchain")

    meta = {}
    for n in new:
        r = found[n]
        meta[n] = {
            "name": n,
            "url": r["html_url"],
            "language": r.get("language"),
            "size_mb": round(r.get("size", 0) / 1024, 1),
            "default_branch": r.get("default_branch") or "main",
            "branch_ok": None,
        }

    # 候选可用性预检：仓库可能是空的、default_branch 已被删、或私有且无权访问。
    # 这类候选一旦进到登记环节，git submodule add 必定失败并拖垮整个 workflow，
    # 所以在发现阶段就探一次分支是否存在，让调用方提前跳过而不是等它炸。
    if args.verify:
        for n, m in meta.items():
            m["branch_ok"] = bool(ls_remote_head(f"{OWNER}/{n}", m["default_branch"]))

    if args.json:
        print(json.dumps([meta[n] for n in new], ensure_ascii=False, indent=2))
        return 0

    print(f"发现来源: {source}")
    print(f"账号下 eMP-* 仓库: {len(found)} 个，已登记/排除: {len(known)} 个")
    print()
    if not new:
        print("没有新应用，一切都是最新的。")
        return 0

    print(f"=== 发现 {len(new)} 个未登记候选 ===")
    for n in new:
        m, r = meta[n], found[n]
        flag = "" if m["branch_ok"] is None else (
            "" if m["branch_ok"] else "  [不可用：分支不存在或仓库为空，将被跳过]")
        print(f"  {n:24s} {str(r.get('language') or '-'):10s} "
              f"{r.get('size', 0) / 1024:7.1f} MB  {r['html_url']}{flag}")
    print()
    print("把它们加进 scripts/apps.yaml 后运行：")
    print("    python3 scripts/emp.py sync-submodules")
    return 0


def _gitlink_sha(rel: str) -> str:
    """返回索引里该路径的 gitlink（mode 160000）SHA；不是子模块则为空串。"""
    r = subprocess.run(["git", "ls-files", "-s", "--", rel], cwd=ROOT,
                       capture_output=True, text=True)
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "160000":
            return parts[1]
    return ""


def _gitmodules_paths() -> set[str]:
    gm = ROOT / ".gitmodules"
    if not gm.exists():
        return set()
    return {ln.split("=", 1)[1].strip()
            for ln in gm.read_text(encoding="utf-8").splitlines()
            if ln.strip().startswith("path = ")}


def cmd_sync(args) -> int:
    """按 apps.yaml 补齐缺失的子模块。

    注意「已登记」的三种形态：
      1. 本地开发机：目录里有 .git（真正检出过）
      2. CI 全新 checkout：空目录 + 索引里的 gitlink + .gitmodules 条目，
         目录里没有 .git —— 此时再跑 `git submodule add` 会直接
         fatal: '<path>' already exists in the index（曾经的 CI 失败原因）
      3. 半残：.git/modules/<path> 存在但工作区没检出
    所以判定「要不要 add」必须看 .gitmodules / 索引，而不是只看目录里有没有 .git。
    """
    registered = _gitmodules_paths()
    failures: list[str] = []

    def fail(rel: str, detail: str) -> None:
        """单个应用出问题。

        默认（本地手工执行）直接中止，错误要刺眼；
        --tolerant（CI 使用）则记下来继续处理其余应用 —— 一个新仓库建错了
        不该让整条流水线变红，更不该挡住同批次里其它正常候选。
        """
        lines = [ln for ln in (detail or "").strip().splitlines() if ln.strip()]
        brief = lines[-1] if lines else "未知错误"
        if args.tolerant:
            failures.append(f"{rel}: {brief}")
            _warn(f"{rel} 跳过：{brief}")
            return
        print(detail, file=sys.stderr)
        raise SystemExit(1)

    for a in all_apps():
        rel = a["path"]
        path = ROOT / rel
        url = f"https://github.com/{a['repo']}.git"

        if (path / ".git").exists():
            print(f"[skip] {rel} 已检出")
            continue

        if rel in registered or _gitlink_sha(rel):
            if args.init:
                print(f"[init] {rel} <- {url}")
                r = _git(["submodule", "update", "--init", "--", rel])
                if r.returncode != 0:
                    fail(rel, r.stderr)
            else:
                print(f"[keep] {rel} 已登记为子模块，工作区未检出（跳过 add）")
            continue

        if path.exists() and any(path.iterdir()):
            fail(rel, f"[error] {rel} 目录非空但不是子模块，请先清理后重试\n")
            continue

        if args.dry_run:
            print(f"[would add] {rel} <- {url}")
            continue
        print(f"[add] {rel} <- {url}")
        base = ["submodule", "add"]
        r = _git(base + ["--branch", a["branch"], url, rel])
        if r.returncode != 0:
            # 常见于上次运行被中断，.git/modules/<path> 已存在：
            # 复用本地 git 目录而不是重新克隆
            if "is found locally" in (r.stderr or ""):
                print("      本地已有 git 目录，改用 --force 复用")
                r2 = _git(base + ["--force", "--branch", a["branch"], url, rel])
                if r2.returncode != 0:
                    fail(rel, r2.stderr)
            else:
                fail(rel, r.stderr)

    if failures:
        print(f"\n[共跳过 {len(failures)} 个无法登记的应用]", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print("  这些仓库可能是空的、分支不存在或无权访问；"
              "确认后可在 apps.yaml 的 exclude 名单里登记，避免反复告警。",
              file=sys.stderr)
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


def ls_remote_head(repo: str, branch: str, retries: int = 2) -> str:
    """查某仓库分支的最新提交 SHA（无需 token）。

    网络超时/抖动能靠重试救回来；真失败也只返回空串由调用方决定降级，
    绝不抛异常 —— 这个函数在 bump 步骤里跑，抛出去会把发布流水线整条判红，
    而「拉新指针失败」不该阻塞打包（build-all.sh 本来就按分支最新克隆）。
    """
    url = f"https://github.com/{repo}.git"
    last = ""
    for attempt in range(retries + 1):
        r = _git(["ls-remote", url, f"refs/heads/{branch}"], timeout=60)
        if r.returncode == 0:
            return (r.stdout.splitlines() or [""])[0].split("\t")[0]
        last = (r.stderr or "").strip() or f"exit {r.returncode}"
        if attempt < retries:
            time.sleep(2 * (attempt + 1))
    print(f"[warn] ls-remote {repo}@{branch} 失败: {last}", file=sys.stderr)
    return ""


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
                        "@update(sub): 发布前把子模块拉新到各自最新 main\n\n"
                        + body + "\n\nCo-Authored-By: Claude <noreply@anthropic.com>"],
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
    d.add_argument("--verify", action="store_true",
                   help="对每个候选预检分支是否存在（空仓库/分支删除会标 "
                        "branch_ok=false），多几次 ls-remote 往返")
    d.set_defaults(func=cmd_discover)

    s = sub.add_parser("sync-submodules", help="按清单补齐缺失的子模块")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--init", action="store_true",
                   help="对已登记但工作区未检出的子模块执行 "
                        "git submodule update --init")
    s.add_argument("--tolerant", action="store_true",
                   help="单个应用登记失败不中止（CI 用），最后汇总跳过项")
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
