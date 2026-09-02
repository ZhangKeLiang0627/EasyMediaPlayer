# EasyMediaPlayer
## Author：@kkl

---

## 克隆

```
git clone --recursive https://github.com/ZhangKeLiang0627/EasyMediaPlayer

git submodule update --init --recursive
```

## CI/CD 自动构建（GitHub Actions）

固件不在本仓库手工编译，而是由 GitHub runner 用 `eMP-toolchain` 交叉编译后，
打包成 `firmware.tar.gz` 作为 Release 产物发布。**完全不依赖本地 VM / Windows。**

### 触发方式
- 推送 `v*` 标签：`git tag v1.0 && git push origin v1.0` → 编译并挂到同名 Release。
- 手动触发（Actions 页面 → Build firmware → Run workflow）：只产出 artifact，不发布 Release。

### 工作原理
1. `setup-t113-toolchain.sh` 下载 `eMP-toolchain` 的 `tc_toolchain.tar.gz` + `tc_sysroot.tar.gz`，
   解压后用符号链接把各 app `Makefile` 里写死的 `/home/hugokkl/tina-sdk/...` 与
   gcc wrapper 写死的 `/home/caiyongheng/tina/...` 映射到解压目录，**零改动 app 仓库即可编译**。
2. `build-all.sh` 读取 `scripts/apps.yaml`，对每个 `enabled: true` 的应用
   `git clone --depth 1` 后用其自带 `Makefile`/`CMakeLists` 交叉编译，产物放进 `firmware/`。
3. 把 `firmware/` + `image/` 打包成 `build/firmware.tar.gz` 上传。

### 新增应用（自动发现）
账号下新增 `eMP-*` 仓库后，两种方式登记：
- 手动：在 `scripts/apps.yaml` 追加一项，再 `python3 scripts/emp.py sync-submodules`。
- 自动：`Sync submodules` 工作流每周一扫描，发现未登记仓库会开 PR（默认 `enabled: false`，
  需人工确认后改为 `true` 才进入固件，避免把 CI 弄坏）。

### 本地验证脚本
```bash
python3 scripts/emp.py list            # 列出将参与编译的应用
python3 scripts/emp.py check           # 校验 apps.yaml 与 .gitmodules 一致
python3 scripts/emp.py discover        # 扫描账号下未登记的新应用
./scripts/build-all.sh                 # 本地完整跑一遍 CI 逻辑（需 Linux + 网络）
```

## 文件树

```
UDISK
├─ font           // 字体
├─ video          // 视频
├─ music          // 音乐
│  └─ lyrics      // 歌词
├─ picture
│  ├─ album       // 相册
│  ├─ cover       // 封面图
│  ├─ gif         // GIF图
│  └─ icon        // 图标
└─ config         // 系统设置
   └─ sysconfig.json
```



## FAQs

- Q1：出现执行`./build.sh`时报错`./build.sh: line 2: $'\r': command not found`。

> A1：莫慌，来上一段`sed -i 's/\r$//' build.sh`即可，这时你重新执行`./build.sh`肯定解决问题啦！


## 鸣谢
- https://gitee.com/Jumping99/minipad/ - 提供软件框架
- https://github.com/FASTSHIFT/X-TRACK - 提供UI框架
- https://oshwhub.com/fanhuacloud/t113-s3-86panel - 提供开源硬件 