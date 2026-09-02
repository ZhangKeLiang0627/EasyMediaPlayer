# EasyMediaPlayer
## Author：@kkl

---

## 克隆

```
git clone --recursive https://github.com/ZhangKeLiang0627/EasyMediaPlayer

git submodule update --init --recursive
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