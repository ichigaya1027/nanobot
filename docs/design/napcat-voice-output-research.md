# NapCat 语音发送：上游 PR 与协议调研

查证日期：2026-10-23。本地 `upstream` 指向 `HKUDS/nanobot`，`origin` 指向 `xiaoxuan010/nanobot`。本文核对 GitHub PR 的当前状态与实际改动，以及 NapCat 官方协议文档和源码。用户已选定阿里云百炼 `qwen-audio-3.1-tts-plus` 和自定义音色；本文只研究语音发送协议与现有实现的可复用范围。

## 结论

检索范围内没有找到可以直接补齐本项目 NapCat 原生语音发送和 GAF 动作工具的现成 PR。已有候选分别实现 Telegram 语音、Discord 音频附件、官方 QQ botpy 语音类型，或通用 TTS 生成；它们没有修改本项目使用的 NapCat `record` 发送路径。应借鉴接口职责划分，按现有 NapCat 动作契约补齐发送能力，避免为了单个已选定的 TTS API 引入其他渠道或多供应商框架。

NapCat 已原生支持 OneBot `record` 消息段，并承担音频转 Silk、上传和构造 QQ PTT 元素。nanobot 可以传 MP3/WAV 文件内容，让 NapCat 完成平台编码。若 nanobot 和 NapCat 使用不同文件系统，`base64://` 可以直接携带文件内容，无需增加共享目录或文件 HTTP 服务。以上能力由官方消息格式文档及其实际发送实现交叉确认。[消息类型](https://napneko.github.io/develop/msg#record)、[文件处理](https://napneko.github.io/develop/file#file-%E9%9F%B3%E9%A2%91%E6%96%87%E4%BB%B6%E7%9A%84%E5%A4%84%E7%90%86)、[消息转换源码](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/api/msg.ts)、[文件 URI 解析源码](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-common/src/file.ts)

## 现有 PR 与 issue

状态中的“关闭”均表示关闭且未合并，不能据此认为相关能力已经进入上游。

| 候选 | 查证状态 | 实际改动与适用范围 | 对本项目的适用性 |
| --- | --- | --- | --- |
| [HKUDS/nanobot#747](https://github.com/HKUDS/nanobot/pull/747) | 已合并，2026-02-17 | 修改 `nanobot/agent/tools/message.py` 与 `nanobot/channels/telegram.py`；媒体路径透传，`.ogg` 选择 Telegram `send_voice`，其他音频选择 `send_audio`。 | 可以参考“渠道负责平台消息类型”的分层。Telegram 的 `send_voice` 和 OGG 约定不能代替 NapCat `record`。 |
| [HKUDS/nanobot#2316](https://github.com/HKUDS/nanobot/pull/2316) | 已关闭，未合并 | 语音部分在 `nanobot/channels/qq.py`，增加 `QQ_FILE_TYPE_VOICE=3` 和扩展名/MIME 判定；使用官方 QQ botpy 富媒体接口。当前 diff 共 20 个文件，包含其他不相关改动。 | 这是官方 QQ Bot API，不是 NapCat/OneBot。不能直接 cherry-pick 成本项目的语音发送补丁。PR 作者也指出，仅靠平面 `media` 路径无法让模型明确选择语音或普通文件。 |
| [HKUDS/nanobot#1306](https://github.com/HKUDS/nanobot/pull/1306) | 开放，未合并 | 新增 `nanobot/agent/tools/tts.py` 的 `speak` 工具和 `nanobot/providers/tts.py`；修改 Discord 发送和 Agent 接线。提供 Groq TTS、Edge 回退及 OGG 转码，声明 Discord 产物为可播放附件。 | 可参考模型显式选择语音动作。代码经 `bus.publish_outbound` 排队后即宣称发送，且操作 `MessageTool._sent_in_turn`；与本项目通过 NapCat 同步回执记录动作成功的 GAF 契约不同。PR 自身也不保证 Discord 原生语音气泡。 |
| [HKUDS/nanobot#4316](https://github.com/HKUDS/nanobot/pull/4316) | 已关闭，未合并 | 修改 `nanobot/agent/tools/message.py` 增加 `tts` 参数，通过 `_tts` 元数据传递；新增 `nanobot/audio/tts.py`、`tts_registry.py`、`nanobot/providers/tts.py` 以及配置和设置 API；在 Telegram 消费该标志。 | 展示了“一个发送调用内部合成”的做法，但没有 NapCat/GAF 接线，而且增加完整多供应商配置体系。对已选定单个 API 的需求，直接引入范围过大。 |
| [HKUDS/nanobot#4560](https://github.com/HKUDS/nanobot/pull/4560) | 已关闭，未合并 | 仅新增 `nanobot/audio/tts.py`，定义生成本地音频路径的 `TTSTool`，探测 Edge、系统 TTS 等命令；没有 NapCat 发送实现。 | 不适用于已选定的远程 API，亦未解决发送和 GAF 动作结果。维护者明确表示不继续接收该 PR，不能作为即将合并的依赖。 |
| [HKUDS/nanobot#4010](https://github.com/HKUDS/nanobot/issues/4010) | issue 开放 | 提议通用语音输出，包含显式 `speak` 和渠道自动语音两种模式，以及多供应商、转码、缓存等扩展。 | 是功能提案，不是已实现接口。可参考合成与发送分工；本需求由 LLM 选择文字或语音，无需引入自动转换所有回复的渠道开关。 |

上述判断以各 PR 的 [changed files API](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files) 返回与 diff 为依据，并非只看标题。关键差异可直接查阅 [#747 的文件改动](https://github.com/HKUDS/nanobot/pull/747/files)、[#2316 的文件改动](https://github.com/HKUDS/nanobot/pull/2316/files)、[#1306 的文件改动](https://github.com/HKUDS/nanobot/pull/1306/files)、[#4316 的文件改动](https://github.com/HKUDS/nanobot/pull/4316/files)、[#4560 的关闭说明](https://github.com/HKUDS/nanobot/pull/4560#issuecomment-4815664027)。

检索使用 `repo:HKUDS/nanobot is:pr` 配合 `napcat`、`voice`、`audio`、`tts`、`record` 和 `语音`，并交叉检查 `voice napcat`、`audio QQ`。`xiaoxuan010/nanobot` 中没有检索到相关 voice PR。原生 NapCat 接入 PR [#3509](https://github.com/HKUDS/nanobot/pull/3509) 与 [#4146](https://github.com/HKUDS/nanobot/pull/4146) 已合并；这只能说明渠道接入存在，不说明它已经支持语音出站。

## NapCat 发送契约

### 消息类型与 API

原生 QQ 语音使用 `record`，不是 `file`。`send_msg`、`send_group_msg` 和 `send_private_msg` 使用常规消息数组，`record.data.file` 放文件 URI。下例展示应用发出的单个请求结构；实际文件内容由 nanobot 编码，不交给模型构造。[消息类型](https://napneko.github.io/develop/msg#record)、[API 列表](https://napneko.github.io/onebot/api)、[`SendMsg` schema 和处理函数](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/action/msg/SendMsg.ts)

```json
{
  "action": "send_msg",
  "params": {
    "message_type": "group",
    "group_id": "123456789",
    "message": [
      {
        "type": "record",
        "data": {
          "file": "base64://<encoded audio bytes>"
        }
      }
    ]
  },
  "echo": "<request id>"
}
```

成功响应数据包含 `message_id`。源码在构造消息元素后等待 `sendMsgWithOb11UniqueId`，后者等待 QQ kernel 的成功状态，再返回消息 ID。因此 GAF 可以沿用现有“实际发送回执成功后记录动作成功”的流程，而不把“TTS 生成完成”或“加入出站队列”当作已发送。[OneBot 发送处理](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/action/msg/SendMsg.ts)、[OneBot 回执包装](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/api/msg.ts)、[kernel 成功事件等待](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-core/apis/msg.ts)

### 文件传输

`record` 复用文件类消息处理：选择 `url`、`file` 或 `path`，调用 `uriToLocalFile`，再交给语音元素生成函数。URI 解析支持 NapCat 可访问的本地路径、HTTP(S)、`file://` 和 `base64://`。本地绝对路径指 NapCat 所在机器或容器内的路径；nanobot 自己磁盘上的路径不会自动对远端 NapCat 可见。`base64://` 将音频传至 NapCat 临时文件后进入同一编码流程，适合复用本项目现有的跨主机图片传输方式。[消息文件处理](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/api/msg.ts)、[URI 处理](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-common/src/file.ts)

官方还提供 `upload_file_stream` 处理大文件和跨设备部署。当前短句 TTS 需求不依赖它；如后续明确要求发送大型音频，再评估是否切换传输方式。[文件处理文档](https://napneko.github.io/develop/file)

### 音频格式与转码归属

`createValidSendPttElement` 调用 `encodeSilk`，上传生成的文件，并构造 `ElementType.PTT`。`encodeSilk` 检测真实 Silk 格式：已是 Silk 则复用；其他输入统一交给 NapCat 的 FFmpeg 服务转成 NT Silk，再读取编码后的时长。这里按音频内容处理，不靠 `.silk` 扩展名跳过编码。[PTT 构造](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/api/file.ts)、[Silk 转码入口](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-core/helper/audio.ts)、[格式检测接口](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-core/helper/ffmpeg/ffmpeg.ts)

MP3 和带文件头的 WAV 可以交给该解码流程；nanobot 无需先转换成 OGG 或 Silk。Exec 适配器给 FFmpeg 传入 `-i inputFile`，输出使用单声道、24 kHz、`ntsilk_s16le`；Addon 适配器同样只接受输入和输出文件路径。无头 PCM 缺少采样率、声道数和采样格式信息，这条接口没有为输入提供这些参数，因此不能将“返回任意 PCM 字节”视为已支持。若已选定的 TTS API 可返回 MP3/WAV，优先选择其一；若只返回 PCM，需先确认其确切参数并封装成 WAV。[Exec 适配器](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-core/helper/ffmpeg/ffmpeg-exec-adapter.ts)、[Addon 适配器](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-core/helper/ffmpeg/ffmpeg-addon-adapter.ts)

转码错误会向上抛出。发送动作应将其作为本次语音发送失败返回，继续遵守既有工具结果与 `end_response` 判定；不应自动改发文字来制造另一项模型没有选择的动作。NapCat 自己的编码用例也明确验证了转码错误传播。[编码入口与用例](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-test/audioEncoding.test.ts)

### 语音与引用、文字混合

普通 `send_msg` 的 schema 接受混合消息数组；实现会把 `record`、`reply`、`text` 分别转换为 QQ 元素，整组提交 kernel，没有为普通消息单独拆分语音。因此源码可以构造混合请求。但官方文档未给出“引用语音”和“同一条语音带文字”在 QQ 客户端上的显示保证，仅检查数组 schema 不能确认最终呈现。首期发送纯 `record` 可以完整满足原生语音需求；引用语音或混合消息应在有明确需求时单独验收。[消息数组 schema](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/types/message.ts)、[`SendMsg.base_handle`](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/action/msg/SendMsg.ts)、[元素转换](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/api/msg.ts)

## 对本次设计的约束

- TTS API 适配只负责把文本变成已明确格式的音频；NapCat 渠道负责把音频作为 `record` 发出。生成成功与发送成功是两个状态。
- 模型选择语音应落到现有 GAF 动作工具流程，返回 NapCat 的实际消息 ID，并复用动作去重、自身消息观察、动作结果记录和 `end_response` 语义。
- 应让模型在一次语音动作调用中表达说什么，由执行端完成合成和发送；无需让模型复制本地路径、Base64 或 OneBot 数据结构。
- TTS 服务故障、NapCat 转码失败和发送失败都应返回可读工具错误；全部工具调用成功且至少一次请求结束时，才满足既有结束回应条件。
- TTS 适配以用户选定的百炼 API 为准，采用其 WAV 产物进入 NapCat 转码流程；PR 中的 Groq、Edge 或 OpenAI 参数只用于理解候选实现，不作为本项目的供应商配置。

## 后续验收要覆盖的外部行为

先用选定 TTS API 生成一段真实短音频，再经部署实例的 NapCat 发到授权测试群，检查 QQ 客户端显示为可播放语音，并核对平台 `message_id` 与 GAF 动作记录。当前材料是协议和源码证据，不能证明部署实例的具体 NapCat 构建已经可以解码选定 API 的真实产物；这项验收负责排除音频格式或 NapCat 编码组件不兼容造成的语音发送失败。
