# 设计与实现边界

## 目标与组成

素材发现不是一个单独的搜索 API。它把剪辑意图、检索、证据、质量判断和选片时间码连接起来。实现位于 `asset_discovery/`：

- `planning.py`：脚本需求结构、路由、文字/向量混合召回、显式 Agent 决策与自动评分。
- `media.py`：FFprobe 元信息、FFmpeg 场景变化检测、镜头内分段、三时点抽帧、SRT、音量与图像指标、增量索引。
- `providers.py`：Commons/Freesound/Pexels/Pixabay 官方 API、小批量查询、逐项许可证核验、有限重试、下载与证据记录。
- `rights.py` / `stock.py` / `web_import.py`：商业编辑许可策略、平台 API 与网页证据导入。
- `intelligence.py`：可选帧序列视觉理解、音频输入理解、ASR、文本向量和多模态重排。默认不启用。
- `exporting.py`：可播放审片包、标准化裁切、JSON/CSV/FCP7 XML/Remotion 组件。
- `core.py`：SQLite 与文件状态、哈希、公共媒体探测。

没有后台扫描、常驻服务、自动遥测或自动模型下载。用户明确指定根目录；符号链接文件不索引。所有任务同步执行。一个项目只允许一个写入进程，不并发运行导入/索引/下载。

## 默认 Agent 模式

脚本 → Agent 修订需求 → 本地镜头索引 → 文字召回候选 → Agent 查看帧/试听 → 导入审片记录 → Agent 按具体需求重排并选择镜头内子片段 → `choose` 校验 → 导出。

语义判断来自实际阅读脚本和查看媒体的宿主 Agent，命令行不会暗中调用云 API。Agent 看图仍经由当前宿主能力，不能称作纯离线模型。只有本地模型服务且工具执行环境也离线时，才是本地推理。

自动 `assemble` 是备选：

`score = 0.65 × relevance + 0.15 × aesthetic + 0.10 × usability + 0.10 × technical`

文字相关度采用英文词与中文二元字串的覆盖率。启用向量后相关度为 `0.3 × 文字覆盖 + 0.7 × max(0, cosine)`。可选多模态重排再融合 `0.65 × 模型相关度 + 0.35 × 原排序分`。这是可解释的启发式，没有经过用户真实数据标定，不应当作普适质量模型。

索引为 SQLite 持久化，每镜头的描述、字幕、审片标签、可选 embedding 随片段保存。向量检索逐片段线性比较，适合 MVP 中小库；不是 ANN/百万级检索引擎。Embedding 模型和 endpoint 组成版本标识，换模型不会混用旧向量。

## 分段与质量

FFmpeg 场景阈值默认 0.32；硬切之间最长 8 秒，较长镜头等分。每段采样 15%、50%、85% 三个位置，640px 宽图供视觉模型/Agent；另降采样为 64×64 灰度，计算暗/亮像素比和拉普拉斯方差。音频读取峰值与平均音量。

这些是诊断信号：低纹理不一定失焦，黑场可能有剪辑用途，峰值接近零不证明削波。默认仅分辨率、已明确拒绝/合成冲突、时长等构成硬筛选，其余交由审片判断。审片置信度 <0.5 默认不能自动选择。真实摄影无法仅靠 `synthetic=false` 保证，需描述证据。

逐镜头分段不会准确切出所有转场、微动作或音效起音；Agent `choose` 可指定更精准的源入点。ASR 只有片段级时间范围，未实现逐字强制对齐。SRT 输入支持原始时间码，索引时分配到相交镜头。

## 增量与错误处理

原文件全量 SHA-256，加 sidecar 哈希和场景设置构成指纹，未变化不重复抽帧；首轮和复扫都会读取文件内容计算哈希，这对大型库有 I/O 成本。原文件变化会更新片段并清除旧审片/向量。无效文件隔离到错误列表并移除旧索引；删除文件后索引清理。索引错误退出码 2，不伪装全部成功。

本地文件夹里的同字节不同路径会各自保留；`assemble` 只防止同一个 segment ID 重复使用，不是跨文件感知去重。Agent 选片时应避免内容重复；没有实现感知哈希去重。

## 可选模型配置

修改项目 `config.json` 的 `ai` 字段，其他配置保留：

```json
{
  "base_url": "http://127.0.0.1:1234/v1",
  "model": "你的视觉模型ID",
  "embedding_model": "你的多语言文本向量模型ID",
  "transcription_model": "你的ASR模型ID",
  "audio_model": "支持input_audio的模型ID或留空",
  "key_env": "ASSET_AI_KEY",
  "allow_remote_upload": false
}
```

协议：视觉 `POST /chat/completions`，按时间排列 JPEG `image_url`；音频理解为相同接口的 `input_audio` WAV；向量 `POST /embeddings`；ASR `POST /audio/transcriptions` multipart。均非依赖任何特定品牌 SDK，服务必须真实支持相应接口。`describe` 的视觉模型不会监听视频声轨，想识别语音应另外 `transcribe`；纯音频理解须配置 `audio_model`，否则明确跳过。

```sh
python3 scripts/assets.py --project ./my-project describe --limit 10
python3 scripts/assets.py --project ./my-project transcribe --limit 10
python3 scripts/assets.py --project ./my-project embed --limit 100
python3 scripts/assets.py --project ./my-project search "雨夜街道倒影" --embeddings --rerank
```

默认仅接受 loopback HTTP；远程 HTTPS 还必须 `allow_remote_upload=true`。这会发送抽帧/相关元信息、音频或文本，可能产生费用。每次有数量上限，失败不自动换供应商或重试收费请求。本次未实际连接视觉、音频或向量模型，协议模拟通过不等于模型效果已验证。

## 下一阶段应按真实问题扩展

先接入用户指定的录屏/实拍/音效各一小批，记录每次需求、候选、最终采用片段与拒绝理由。再决定是否需要 OCR、本地 ASR、跨语言向量、感知去重和 ANN；不要在质量尚未验收前大规模扩库。
