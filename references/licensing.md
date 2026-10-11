# 在线来源与许可策略（0.2）

核实日期：2026-10-09。默认 `commercial_edit`：接受适用于商业视频编辑的明确许可，保留各自条件，不再只接受 CC0。`strict_cc0` 仍可手动选择。用途默认 `web_video`，面向网络视频。

## 实际接入范围

| 来源 | 搜索与下载方式 | 接受范围 |
|---|---|---|
| Pexels | 视频官方 API；也可 Agent 网页逐条处理 | Pexels License |
| Pixabay | 视频官方 API；音乐/音效走网页流程 | Pixabay Content License |
| Mixkit | Agent 网页查找、正常下载、凭页面证据登记 | Video Free、Music Free、Sound Effects Free；Restricted 不自动放行 |
| Wikimedia Commons | 官方 API 音视频搜索与原件下载 | 元数据明确的 CC0、CC BY |
| Freesound | 官方 API 音效搜索；MP3 预览或 OAuth 原件 | CC0、CC BY；API 使用资格独立检查 |

不自动接受 NC、ND、ShareAlike、未知许可或 Public Domain Mark；它们不等于一律不能用，而是需要另外判断义务，本版不自动处理。CC BY 自动生成作者、来源、许可及修改说明，发布时仍需实际放置这些署名。

## API 适配

Pexels 使用 `PEXELS_API_KEY` 请求头，路径为 `https://api.pexels.com/v1/videos/`。保存条目作者、原页面和 Pexels License；其 API 不提供每条素材的 CC0 声明，所以状态记为 `official_api_item_under_provider_terms`，不能标为 CC0。素材用于编辑作品，不能做独立素材转售或竞争图库。来源：[API 文档](https://www.pexels.com/api/documentation/)、[许可](https://www.pexels.com/license/)、[条款](https://www.pexels.com/terms-of-service/)。

Pixabay 使用 `PIXABAY_API_KEY`，官方请求要求 key 查询参数；工具不把带 key 的 URL 写入缓存/输出，API key 请求禁止重定向，连接报错省略 URL。视频搜索与详情遵循官方的 24 小时缓存要求，下载前重新执行本地许可策略并获取有效期内的官方详情缓存，缓存过期后才刷新，不谎称每次都实时重查。公开 API 文档仅列图片/视频，本版不会构造不存在的音频接口。出处：[API](https://pixabay.com/api/docs/)、[Content License](https://pixabay.com/service/license-summary/)、[条款](https://pixabay.com/service/terms/)。

API 搜索输出和审片页保留平台来源、作者和原页面；导出 `CREDITS.md`。这些记录也便于后续核对许可与声明。

Freesound 的音频许可和 API 使用资格仍分别检查，不能用“声音可商用”代替接口商用协议。`FREESOUND_API_KEY` 用于搜索/详情，`FREESOUND_OAUTH_TOKEN` 用于原件；默认 HQ MP3 是预览。`online.freesound_api_use` 仍默认 `unconfirmed`，有真实资格才设置 `noncommercial` 或 `commercial_agreement`（后者还需协议记录）。参考 [API 条款](https://freesound.org/help/tos_api/)、[资源文档](https://freesound.org/docs/api/resources_apiv2.html)。

## 网页接入与证据

没有配置 Pexels/Pixabay Key 时可运行 `online-search ... --browser`；Mixkit 与 Pixabay 音频自动返回 `browser_assisted` 任务，包含站点入口和限定站点查询词。**这只生成下一步任务，不是已经找到结果。** 宿主 Agent 随后使用真实搜索/浏览器工具查看具体条目，再通过正常下载按钮获取所需的少量文件。

保存实际条目/具体下载版本显示的许可证截图、文本或下载凭证。填写 `examples/web-receipt.json` 后调用 `import-web 文件 凭证.json`。程序检查来源域名、许可类别、媒体类别、文件 SHA-256、证据存在性和当前用途，再将素材与证据复制到项目目录。这里的许可核验来自 Agent/用户实际阅页，状态为 `agent_or_user_page_review`；程序无法通过一张截图的存在就证明页面判断正确，不得编造凭证。

Mixkit 的视频有 Free/Restricted 两类，同一条目不同下载选项须核对所选版本。本版禁止 Restricted 自动用于商业编辑。Music Free 可用于网络视频、社交平台、播客等，但不允许游戏、电视/广播、光盘等用途；`intended_use` 不为 `web_video`/`podcast` 时阻止该类音乐。SFX 的许可范围与音乐不同，分别记录，不混用。许可说明：[分类](https://mixkit.co/license/)、[视频 Free](https://mixkit.co/license/modal/videoFree/)、[音乐](https://mixkit.co/license/modal/musicFree/)、[音效](https://mixkit.co/license/modal/sfxFree/)。

Mixkit 不做脚本批量抓取或图库镜像，按用户具体项目逐条处理，遵循 [用户条款](https://mixkit.co/terms/)。付费跳转、登录或验证码需要正常完成，不绕过。

## 工作文件与最终发布

非 CC0 平台素材可用于符合许可的创作，但不表示可以把原始/轻微裁切的文件当成素材包向外分发。导出的 `public/assets` 是**本地剪辑工作文件**。特别是 Mixkit SFX，不应作为模板、工具或源文件素材分发。交付最终视频与交付原始素材包须区分；若客户要工程源文件，需要逐条核对许可。

所有许可核验都不自动解决肖像、商标、隐私或上传者权属问题。对具体商业画面保留必要人工判断；平台声明和条款关联不是工具取得全部权利的证明。

## 限量访问

网络默认关闭。官方 API 开启后每次默认 5 条，硬上限 20，不自动翻页；串行至少一秒间隔；429/502/503 有限重试；单文件默认 150 MB。下载地址仅限支持来源的 HTTPS 主机，域名不明则停止。网页任务不从 Python 发网络请求。

CC 许可字段匹配标准网址且禁止仿冒域名；Commons 的短名与 URL 必须一致。CC BY 缺失作者或来源时不自动接收。改变项目许可模式后，搜索、选片和导出会按新模式重新判断。
