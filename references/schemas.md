# 文件格式与约定

全为 UTF-8 JSON。源时间码单位为**秒**，源片段按 `[source_in, source_out)` 表示；导出时间线单位为项目帧。文件路径使用绝对路径，交付包 `public/assets` 为可迁移的媒体目录。移动原库后重新索引；不要手改 SQLite 中的路径。

## 项目目录

```text
config.json           项目配置（无密钥）
index.sqlite3         原始文件、镜头、描述、审片、可选向量
frames/               抽帧缓存
review/               可播放预览、审片模板、证据包
online-cache/         有限在线查询结果与来源证据
 downloads/           下载的素材及 .license.json / .asset.json
plan.json             视频需求计划
selection.json        已选择片段与 unresolved 缺口
```

索引不修改原文件。不要把项目状态文件夹作为原素材根目录，避免再次索引导出的裁切片段。

## plan.json

```json
{
  "method": "agent_refined",
  "needs": [
    {
      "id": "shot-001",
      "query": "手指按下机械键盘，近景，真实拍摄 keyboard close up typing",
      "online_query": "hands typing mechanical keyboard close up",
      "kind": "video",
      "route": "local_first",
      "duration": 3,
      "at": 0,
      "must": [],
      "avoid": ["animation"],
      "real_only": true
    }
  ]
}
```

`id` 唯一且仅允许字母、数字、下划线、连字符；`kind` 为 video/audio。`local_only` 禁止在线替代；`online_only` 禁止本地；`local_first` 优先本地。`duration` 为所需可用时长，`at` 为目标时间线入点。同一类素材仅支持一条不重叠轨道；视频和独立音效可重叠。

`must/avoid` 是检索文字中的不区分大小写的字面子串约束，不是模型视觉事实断言。仅在审片描述已准确表达需要验证的事实时才可依赖，否则由 Agent 人工决策。`real_only` 会排除审片标为 synthetic 的素材，但不是 AI 生成检测器。

## 本地 sidecar

原始文件 `/素材/clip.mov` 可有 `/素材/clip.mov.asset.json`：

```json
{
  "description": "我拍摄的桌面操作",
  "tags": ["键盘", "hands", "owned footage"],
  "rights": "owned",
  "segments": [
    {"start": 1.2, "end": 4.8, "description": "手指连续敲击键盘，屏幕虚化"}
  ]
}
```

有 `.srt` 时可命名 `clip.mov.srt` 或 `clip.srt`，前者优先。sidecar 的 `segments` 是描述覆盖范围，不自动替代镜头检测边界。完整审片最好通过 `import-review` 导入以绑定内容哈希，不要靠旧文件名复用审片结论。

## 审片记录

```json
[
  {
    "id": "从review-packet复制",
    "sha256": "从review-packet复制的原文件SHA256",
    "review": {
      "description": "实际看到或听到的具体内容，以及不确定之处",
      "tags": ["中文语义词", "English synonyms"],
      "aesthetic": 0.7,
      "usability": 0.8,
      "confidence": 0.9,
      "reject": false,
      "synthetic": false,
      "has_people": true,
      "has_logos": false
    }
  }
]
```

三个分数均为 0..1。`confidence` 表示描述证据的把握程度。`reject` 是该片段明显不可用，不应仅因“不符合这一个查询”就全局拒绝。仅看抽帧时写明采样限制；音效未试听不能描述听感。`import-review` 先验证整批 ID/hash/schema，再写入，防止前半批成功后半批失败。

## decisions.json / choose

按 README 的示例提供 `need_id, segment_id, source_in, score, reason`。`source_in + need.duration` 必须落在索引镜头内部。`choose` 不用字面匹配覆盖掉 Agent 的语义判断，适合跨语言、隐喻、视觉类比和镜头内部择段。Agent 应在理由中记载可观测证据，避免没有依据的高分。

自动 `assemble` 用相关度+质量规则并保留未解决需求；不自动访问网络。Skill 负责根据 `unresolved` 决定下一步检索任务。

## 可追溯性

`selection.json` 保存原始路径/哈希、源入出点、目标时间线位置、审片描述、来源证据和选择理由。`manifest.json` 同时保存归一化裁切文件的 SHA-256。导出前重新计算原件哈希；发生变化则停止，必须重新索引与选片。
