# Asset Discovery · AI 视频素材发现 Skill

[![Tests](https://github.com/guangjun5952/asset-discovery/actions/workflows/tests.yml/badge.svg)](https://github.com/guangjun5952/asset-discovery/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**将脚本需要的画面，连接到本地或在线素材的具体几秒。** 适用于 Codex、Claude Code 及后续 Remotion / FFmpeg / Resolve 剪辑工作流。当前版本：MVP 0.2.0。

这是可执行的 Skill 和素材检索工具包。**默认：本地优先、Agent 看图审片、在线与额外模型 API 均关闭。** 不需要 Python 第三方依赖；需 Python 3.9+、FFmpeg 和 ffprobe。

支持：脚本需求分配 → 本地镜头切分 → 抽帧/字幕/音频指标 → 审片 → 语义选片 → 秒级源时间码与帧级时间线 → 实际媒体裁切与导出。

## 安装

先安装 Python 3.9+ 和 FFmpeg（其中包含 ffprobe），然后获取代码：

```sh
git clone https://github.com/guangjun5952/asset-discovery.git
cd asset-discovery
python3 scripts/assets.py doctor
```

macOS 可用 `brew install ffmpeg`；Ubuntu 可用 `sudo apt-get install ffmpeg`。在仓库目录运行安装器：

```sh
python3 scripts/install.py --target codex
# 或者装给 Claude Code：
python3 scripts/install.py --target claude
```

目标分别为 `~/.codex/skills/asset-discovery`、`~/.claude/skills/asset-discovery`。已存在的目录不会被覆盖。也可通过 `--destination /自选/skills` 安装到指定父目录。安装后开启新聊天让宿主发现 Skill。

在 Codex / Claude Code 中直接说：

> 使用 $asset-discovery，为这个脚本找素材。我的素材目录是「绝对路径」。先找本地拍摄和录屏；不足的再查适合本项目用途的在线素材。使用 Agent 看图审片，不接额外云模型。交付片段、时间码和剪辑清单。

## 当前状态

- 本地索引、Agent 审片记录、选段、裁切及 FFmpeg 合成已用合成素材验证；42 项测试覆盖原有功能与来源扩展。
- Pexels / Pixabay / Commons / Freesound 的 API 适配器有模拟测试，尚未完成全部真实账号搜索下载验收。
- Mixkit、Pixabay 音频和 `--browser` 返回网页任务；需要宿主 Agent 的搜索/浏览器工具继续执行，不是独立网页爬虫。
- Remotion 组件及 Resolve XML 已生成；尚未在实际 Remotion 工程与 Resolve 应用内完整验收。
- 代码采用 MIT；下载素材依各自许可使用，不因本仓库开源而变成 MIT 或 CC0。

## 五分钟验证

```sh
python3 scripts/assets.py doctor
python3 scripts/demo.py ./asset-demo
```

打开 `asset-demo/review/review.html`，观看彩色测试图和全黑候选、试听正弦测试音。让 Agent 读取 `review-packet.json` 的实际图片，填写 `review-template.json` 的描述、评分和是否拒绝。测试音是合成信号，测试图不是实拍素材；此演示验证管道，不验证现实世界检索质量。

```sh
python3 scripts/assets.py --project ./asset-demo/project import-review ./asset-demo/review/review-template.json
python3 scripts/assets.py --project ./asset-demo/project assemble ./asset-demo/project/plan.json
python3 scripts/assets.py --project ./asset-demo/project export ./asset-demo/project/selection.json --out ./asset-demo/delivery
python3 scripts/render_timeline.py ./asset-demo/delivery/manifest.json ./asset-demo/delivery/preview.mp4
```

更精准的 Agent 选片用 `choose`，见下方。空白审片模板不能直接导入；这一步有意保留真实的媒体理解门槛。

## 用自己的素材

以下 `my-project` 是项目状态文件夹，不是原始素材库；所有原文件只读。

```sh
python3 scripts/assets.py --project ./my-project init
python3 scripts/assets.py --project ./my-project plan ./script.txt
python3 scripts/assets.py --project ./my-project index "/素材/录屏" "/素材/实拍" "/素材/声音"
python3 scripts/assets.py --project ./my-project search "手部操作键盘 typing keyboard" --duration 3
python3 scripts/assets.py --project ./my-project review --limit 20
```

Agent 修改 `plan.json`、查看 `review/review-packet.json` 中的帧/片段、填好审片数据并导入。然后写 `decisions.json`：

```json
[
  {
    "need_id": "shot-001",
    "segment_id": "从审片包复制真实ID",
    "source_in": 12.5,
    "score": 0.9,
    "reason": "已查看该时间段，能看到手指按下键帽；主体和动作满足需求，画面不含需要裁掉的通知栏。"
  }
]
```

```sh
python3 scripts/assets.py --project ./my-project import-review ./my-project/review/review-template.json
python3 scripts/assets.py --project ./my-project choose ./my-project/plan.json ./decisions.json
python3 scripts/assets.py --project ./my-project export ./my-project/selection.json --out ./delivery
```

`source_in` 是原始文件的秒数，不能超过索引镜头范围。`choose` 检查媒体类别、来源路由、分辨率、审片状态、真实素材约束和时长。没有决策的需求仍留在 `unresolved`。

## 在线搜索与下载：已扩展至五个来源

默认 `online.license_mode` 为 `commercial_edit`，接受 CC0、CC BY 及平台许可，不再限定 CC0。需要原来的严格模式可设为 `strict_cc0`。用途默认 `online.intended_use=web_video`。

| 来源 | 视频 | 音频 |
|---|---|---|
| Pexels | 官方 API / 网页 | 无 |
| Pixabay | 官方 API / 网页 | 音乐、音效走网页 |
| Mixkit | 网页逐条处理 | 音乐、音效走网页 |
| Commons | 官方 API | 官方 API |
| Freesound | 无 | 官方 API |

先看 [来源与许可](references/licensing.md)。官方 API 使用前，在 `config.json` 设置 `online.enabled=true`、真实 `online.contact`。密钥只从环境变量读取：`PEXELS_API_KEY`、`PIXABAY_API_KEY`、`FREESOUND_API_KEY`；不用把它们发进聊天。

```sh
python3 scripts/assets.py --project ./my-project online-search pexels "hands typing keyboard" --out ./pexels.json
python3 scripts/assets.py --project ./my-project online-search pixabay "forest" --out ./pixabay.json
python3 scripts/assets.py --project ./my-project download pexels "从实际结果复制的数字ID"
```

下载后，将返回文件交给 `index` 和审片流程。Pixabay API 搜索/详情缓存 24h，不进行重复实时请求；可选 `online.pixabay_editors_choice=true` 缩小到精选结果，但不是质量保证。

**无 Key / 网页来源：**

```sh
python3 scripts/assets.py --project ./my-project online-search pexels "keyboard" --browser
python3 scripts/assets.py --project ./my-project online-search mixkit "city night" --kind video
python3 scripts/assets.py --project ./my-project online-search pixabay "whoosh" --kind audio
```

命令返回站点入口和查询词，不冒充搜索完成。Agent 使用当前宿主的搜索/浏览器查看具体条目、确认具体版本许可并正常下载；保存截图/文字证据，将 `examples/web-receipt.json` 填为真实记录：

```sh
python3 scripts/assets.py --project ./my-project import-web "/下载/所选素材.mp4" ./receipt.json
```

`import-web` 绑定 SHA-256、记录证据、检查许可/用途并复制到项目目录。Mixkit Restricted 不自动放行；Music Free 的适用渠道与 SFX 不同。CC BY 素材会生成署名草稿。

Freesound 仍需要真实 API 使用资格，`freesound_api_use` 默认 `unconfirmed`；已获商用协议时设 `commercial_agreement` 并保存协议记录。原文件下载需 `FREESOUND_OAUTH_TOKEN` 和 `download --original`，默认 HQ MP3 仍是预览。

## 导出物

| 文件 | 用途 |
|---|---|
| `public/assets/*.mp4, *.wav` | 实际裁切、统一帧率的素材，可直接剪辑 |
| `manifest.json` | Remotion/Agent 读取，含源时间码与时间线帧位置 |
| `clips.csv` | Excel、人工核对、剪辑交接 |
| `resolve.xml` | Final Cut Pro 7 XML，供 Resolve 导入时间线 |
| `AssetTimeline.tsx` | Remotion Composition 组件示例 |
| `CREDITS.md` | 平台来源、CC BY 必须署名及修改说明；最终发布时使用 |
| `provenance.json` | 原文件校验值、来源、授权证据和选择理由 |

FFmpeg 合成示例：`python3 scripts/render_timeline.py ./delivery/manifest.json ./delivery/preview.mp4`。不覆盖已有输出。详见 [剪辑衔接](references/integrations.md)。

## 可选模型能力

无需为默认流程配置。已有本地 OpenAI-compatible 服务时可配置 `ai.base_url` 和相应模型 ID，运行 `describe`、`embed`、`transcribe`；`search --embeddings --rerank` 可做模型检索与重排。不同服务不一定支持全部接口。云端必须显式允许上传，密钥只从环境变量读取。见 [架构与模型](references/design.md)。

## 测试

```sh
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

`doctor` 会检查 FFmpeg、ffprobe 和 XML 解析器；如果 Python 的 expat 动态库报错，请切换到工作正常的 Python 3.9+ 环境。

本 MVP 真实验收范围、未验证项与产物见 [验收记录](references/validation.md)。真实模型接口只做协议模拟测试；没有调用收费模型或批量下载在线素材。后续接入你的素材库后，应以实际找片成功率和返工率衡量效果。


## 参与开发

欢迎提交 Issue 或 Pull Request。请附可复现步骤、运行环境、脱敏后的错误信息，并运行上面的测试。不要上传 API Key、私人录屏、项目索引或未经许可再分发的素材。更改来源适配器时，请附官方接口/条款依据，区分真实调用与模拟测试。

## License

工具代码与文档采用 [MIT License](LICENSE)。第三方素材、平台 API 和模型服务遵循各自条款。项目不提供批量抓取、图库镜像或绕过认证功能。
