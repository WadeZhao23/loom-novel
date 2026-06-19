把一队分工 Agent 织成一条**写小说的流水线**,做成桌面客户端。读你的"外置大脑"一键跑出一章正文;你手改,它**越写越像你**。纯本地,自带 DeepSeek key,稿子不离开你的电脑。

## 怎么用(不写代码也能用)

**Mac** —— 下载 `Loom-mac.zip` → 解压得到 `Loom.app` → **右键 → 打开 → 再点"打开"**(本版未签名,首次必须右键打开,绕过"无法验证开发者";直接双击会被拦)。

**Windows** —— 下载 `Loom-win.zip` → 解压 → 进 `Loom` 文件夹双击 `Loom.exe`(SmartScreen 蓝框时点"更多信息 → 仍要运行")。

打开后:**先点「📖 看看样例」**看一本跑通的书;要写自己的,按欢迎页「🔑 怎么拿 DeepSeek key」填上 key(自带 key,平台按字数计费,几块钱写很久)。

## 说明

- 未做代码签名,所以才有上面的"右键打开 / 仍要运行"一步——开源软件常态。
- 早期版本,生成质量还在打磨,欢迎反馈。

## 开发者 / 从源码跑

```bash
git clone https://github.com/WadeZhao23/loom-novel
cd loom-novel && pip install -e . && loom-app
```

MIT License.
