# 剪辑工作流衔接

## 通用

`export` 会实际裁切转码。MP4 为 H.264 / yuv420p，音轨存在时 AAC；独立音频为 48 kHz 双声道 PCM WAV。项目默认 1920×1080、30 fps，保持原比例并补黑边，不自动裁主体。可在 `config.json` 改为偶数尺寸的竖屏等画幅。MVP 帧率只接受整数 1..120，不输出 drop-frame 时间码。

源时间码保留秒级精度，导出长度和时间线位置四舍五入到项目帧；精度误差不超过约半帧。源 VFR 素材先转 CFR，避免后续按源帧率错误换算。只有分辨率下限，不会因升采样就把素材当高质量。

目前是一条不重叠视频轨、一条独立音效轨，保留视频自带音轨。没有叠加字幕、旁白生成、调色、变速、转场或音量自动闪避。重叠的同类片段在导出前会明确拒绝。

## Claude Code / Codex

安装 Skill 后让 Agent 使用 `scripts/assets.py`；无需 MCP 常驻服务。两类 Agent 都可读 `review-packet.json` 和 `selection.json`，按自身图像/音频能力审片。若当前宿主不能试听，留下音频未审状态或由用户确认，不能填造“听起来干净”。

## Remotion

将导出的 `AssetTimeline.tsx` 与 `manifest.json` 放在同一个源码目录，将导出的 `public/assets` 合入项目 `public/assets`，保留文件名。在入口中 `registerRoot(AssetRoot)`。组件用 `OffthreadVideo`、`Html5Audio`、`Sequence`、`Composition` 与 `staticFile`，适用于支持这些导出的 Remotion 4.x。

素材已经按选中范围裁切，所以组件无需再次套用原始 `source_in`。不要重复裁切，否则会取错片段。时间线位置使用 `from`，时长使用 `durationInFrames`。`absolutePath` 仅供审计，实际播放使用 `staticFile(clip.src)`。

本次没有安装或运行 Remotion 项目的浏览器渲染，组件作为集成入口交付；请在已有项目中运行其正常预览和渲染检查。API 参考：[OffthreadVideo](https://www.remotion.dev/docs/offthreadvideo)、[Html5Audio](https://www.remotion.dev/docs/html5-audio)、[staticFile](https://www.remotion.dev/docs/staticfile)。

## FFmpeg

```sh
python3 scripts/render_timeline.py /交付/manifest.json /交付/preview.mp4
```

直接读取相对 `public/assets` 文件，按时间线补黑场、排列视频并混合源音和独立音效，加限制器避免混音过载。全程通过参数数组调用 FFmpeg，不把文件名插进 shell 命令。已有输出不会被覆盖。

## DaVinci Resolve

导入 `resolve.xml`（Final Cut Pro 7 XML / xmeml version 5），使用导出的 `public/assets` 作为源媒体。XML 使用绝对 file URL，支持含中文/空格路径；把包移到另一台机器后可能需要在 Resolve 里重新链接该目录。该格式不是 Resolve 原生 `.drp`。

所有片段归一化到项目 fps；视频自带双声道放 A1/A2，独立双声道音效放 A3/A4。一个立体声文件引用两个源通道，不丢右声道。导入后的轨道呈现取决于 Resolve 的 XML 导入设置。

本次已解析检查 XML 和相应媒体时长、存在性、解码；**未启动 Resolve 实际导入**。因此不承诺某个版本的导入效果已验收。原始选片与 CSV 不依赖 XML，导入兼容问题不会丢失时间码。
