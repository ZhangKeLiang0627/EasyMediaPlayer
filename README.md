# EasyMediaPlayer
## Author：@kkl

---

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
