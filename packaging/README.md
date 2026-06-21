# 打包成可双击的客户端

目标用户是网文作者,不是程序员——他们不会 `pip install`。这一层就是把 Loom 变成
**双击就开**的 `Loom.app`(Mac)/ `Loom.exe`(Windows)。

## 构建

```bash
# 在项目根,先确保 venv 装好依赖(pip install -e .)
bash packaging/build.sh
```

- Mac → `dist/Loom.app`
- Windows(在 Git Bash / WSL 里跑同一脚本)→ `dist/Loom/`,入口 `Loom.exe`

底层就是 `pyinstaller packaging/loom.spec`。改配置改那个 spec。

## 应用图标 / 应用名

- **图标**:`spec` 的 BUNDLE `icon=` 指向 `packaging/loom.icns`(墨绿底 + 暖金织标)。
  由 `packaging/make_icon.py` 从品牌 weave-mark 生成(纯 Pillow),改色/换样式改脚本再跑:
  `.venv/bin/python packaging/make_icon.py`(重生成 `loom.icns` + `loom/webui/app-icon.png`)。
- **应用名**:Info.plist 的 `CFBundleName=Loom` → 打包后菜单栏/访达显示「Loom」。
- **dev 模式**:从源码 `loom-app` 跑时进程是裸 python,但 `desktop.py` 运行时已把 Dock 图标
  (随包 `app-icon.png`)和**菜单栏名(改写 `CFBundleName`)都换成 Loom**;只有活动监视器 / `ps`
  里进程名还是 `python`(解释器决定),要彻底改名就跑打包好的 `Loom.app`。
- 换了图标后访达可能仍显示旧的(图标缓存):`touch dist/Loom.app` 或重启访达即可刷新。

## 分发(开源、零基建)

应用是**纯本地**的:用户自带 DeepSeek key,稿子和写作指纹都不出本机,所以你**没有任何服务器/存储成本**。分发就是把产物压个包挂出去:

```bash
# Mac
cd dist && zip -r -y Loom-mac.zip Loom.app
# Windows
#   把 dist/Loom 整个文件夹压成 Loom-win.zip
```

挂到 GitHub Releases 即可。

## ⚠️ 没签名 = 用户会撞系统拦截(必读)

未做代码签名/公证时:

- **Mac**:首次打开报"无法验证开发者 / 已损坏"。让用户**右键 → 打开 → 再点打开**(或系统设置→隐私与安全性→仍要打开)。这是开源软件常态,但**会劝退最不技术的那批人**——而那批恰恰是你的核心受众。
  - 若 zip 时漏了 `-y`,Mac 可能直接判"已损坏"。用上面的 `zip -r -y` 保留符号链接。
- **Windows**:SmartScreen 蓝框 → "更多信息" → "仍要运行"。

要做到**双击无警告**,需要付费签名(这就是你"除时间外的成本"真正藏的地方):

- Mac:Apple Developer $99/年,`codesign` + `notarytool` 公证。spec 里 `codesign_identity` 填证书,再走 `xcrun notarytool submit`。
- Windows:OV/EV 代码签名证书(年费,价格不一)。

**建议**:v0.1 先不签,README 里写清"右键打开"三步;等真有稳定用户量、劝退率成了瓶颈,再上 Mac 公证(性价比高于 Windows)。

## 排错

- 闪退看日志:`/tmp/loom-crash.log`(Win 在 `%TEMP%\loom-crash.log`)。
- 想看启动报错:把 `loom.spec` 里 `console=False` 临时改 `True` 重新构建,会带个终端打印异常。
- 界面/模板加载不出来:多半是数据文件没进包,检查 spec 的 `datas` 是否含 `loom/webui`、`loom/templates`。
