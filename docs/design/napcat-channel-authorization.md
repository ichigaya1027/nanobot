# NapCat 群聊与私聊授权分离方案

目标是群聊仅按群名单授权，获准群内任意成员都可参与；私聊入站保留现有用户授权。本文规定待实施的行为与修改范围。

## 当前行为与原因

当前 [`NapcatConfig`](../../nanobot/channels/napcat/runtime.py) 只有 `allow_from`，没有独立群名单。`groupAgent.groups` 选择自主回复模式，其余群继续按 `groupPolicy` 进入普通回复路径。普通路径、自主路径与部分群通知都按发送者检查 `allowFrom`，因此获准用户可以在自主群名单之外触发普通回复。

[`BaseChannel.is_allowed`](../../nanobot/channels/base.py) 依次检查用户通配符、显式用户和已有配对授权。空用户名单仍允许已有配对授权的用户。NapCat 当前没有向 `_handle_message` 传入 `is_dm=True`，本次保留这一行为，不增加自动发送配对码的功能。

## 授权契约

新增 `channels.napcat.allowGroups`，与 `allowFrom` 分别用于群聊和私聊，不作并集或交集运算。

| 场景或配置 | 行为 |
| --- | --- |
| 群聊入站 | 群号在 `allowGroups` 中即可，群内任意成员均可参与 |
| 私聊入站 | 保留 `allowFrom` 和已有配对授权语义 |
| `allowGroups` 缺省或 `[]` | 没有获准群，拒绝全部群聊 |
| `allowFrom` 缺省或 `[]` | 私聊仅允许已有配对授权的用户，不影响群成员 |
| `allowFrom: ["*"]` | 允许任意用户私聊，不影响群范围 |
| 群聊出站 | 目标群必须在 `allowGroups` 中 |
| 私聊出站 | 保留现有发送行为 |

`allowGroups` 本次只接收明确群号。原方案提出的群通配符不是已确认需求，本次不增加；私聊既有通配符继续保留。空群名单表示集合中没有任何群，不回退到 `groupAgent.groups` 或用户名单。

群授权通过后，再按 `groupAgent.groups` 选择自主合批模式，其余获准群继续使用 `groupPolicy`。授权名单与模式名单各自负责一种行为。

## 实现边界

### 消息授权与发布

保留一个必要的基类调整：在 [`BaseChannel`](../../nanobot/channels/base.py) 增加同步方法 `is_message_allowed(sender_id, chat_id, authorization_id=None)`，由 `_handle_message` 调用。默认实现继续选择 `authorization_id` 或 `sender_id`，调用原来的 `is_allowed`。消息构造、配对处理与总线发布保持现有流程。

NapCat 覆写该方法：群地址按群名单判断，私聊按原用户授权判断。真实 `sender_id` 保留在消息中。群授权不经过用户配对查询。这个调整解决基类固定按用户授权与群内任意成员可参与之间的实际冲突，无需复制消息组装代码或加入跳过授权的参数。

### 入站边界

[`_on_message`](../../nanobot/channels/napcat/runtime.py) 解析聊天目标和发送者后，先执行对应授权，再进行模式选择、媒体下载、引用查询、命令处理和观察器入队。`_on_notice` 对现有群通知同样先检查群名单，再处理戳机器人或入群欢迎。

移除 `_observe_group` 和戳机器人路径中的用户名单过滤。机器人自己的消息作为背景输入时也经过群入口授权。命令继续交给现有 Gateway 分发。

观察器只接收已获准的输入，不新增授权回调，不在准备消息和发布批次时重复检查。现有 `GroupObserver.close` 已负责停止时取消计时器并清空等待批次。

### 已有群会话与工具创建

[`NapcatChannel.turn_policy`](../../nanobot/channels/napcat/runtime.py) 对群会话先检查群授权，再判断是否创建自主群工具。未获准时明确抛出权限错误，不能返回 `None` 后继续普通模型执行。现有 [`AgentLoop`](../../nanobot/agent/loop.py) 在模型请求准备前调用该方法，因此使用旧群会话或绑定群会话的定时任务也需要通过群授权。

自主群工具由这里创建，并通过现有 [`GroupRun.group_id`](../../nanobot/channels/napcat/group_tools.py) 绑定当前群。沿用现有的工具参数和消息归属处理，不新增动作授权包装器，也不向背景、转写、媒体回调逐层传递授权状态。在下述停止旧 Gateway 后应用配置的流程中，工具执行期间群名单保持不变。

私聊历史执行和定时执行保持现有行为。此次不修改 `AgentLoop`、`ChannelManager`，不增加所有渠道的停用、启动失败或多实例准入框架。

### 普通发送边界

[`NapcatChannel.send`](../../nanobot/channels/napcat/runtime.py) 在连接检查、普通正文抑制和媒体处理之前，验证群目标是否获准。拒绝使用现有 `DeliveryRejectedError`，让普通回复、进度、通知和 `message` 工具跨群投递共享该边界。私聊发送保留原行为。

入站检查负责外部事件，执行前检查负责已有会话触发，发送检查负责可独立指定的投递目标。三者对应不同的真实入口；内部观察器和已绑定群的工具继续使用这些入口建立的前提。

## 配置、界面与应用方式

在 [`NapcatConfig`](../../nanobot/channels/napcat/runtime.py) 增加 `allow_groups: list[str]`，默认空列表；在 [`manifest.py`](../../nanobot/channels/napcat/manifest.py) 登记 `allowGroups`，并在 [渠道 WebUI](../../nanobot/channels/napcat/webui/index.ts) 与现有语言包中增加群授权字段。字段文案分别使用“允许群聊”和“私聊用户”，说明空名单与私聊配对的实际含义。`groupAgent.groups` 继续表示自主回复群号。

旧配置需要明确填写 `allowGroups`，否则群输入、群会话执行和群发送都被拒绝。不从其他字段推断或自动迁移群名单，不改变已有配对记录。在 [渠道配置指南](../chat-apps.md) 和 [自主回复设计](napcat-group-autonomous-replies.md) 中给出分别配置授权与模式的示例。

应用名单变更时，先停止 Gateway，修改配置，再启动新实例。现有渠道使用构造时读取的配置；本方案不承诺直接修改 JSON 后即时撤权，也不新增实时撤权或任务取消系统。只关闭 NapCat 连接不能终止已经执行的模型和工具任务，因此名单收缩按停止整个 Gateway 的方式应用。

本方案覆盖 NapCat 运行实例提供的群授权。渠道未运行时，`ChannelManager.turn_policy` 当前返回 `None`，所以它不能保证停用渠道的旧会话完全不调用模型；若需要这一独立行为，应另外明确范围并处理。

## 实施分批与验收

第一批只调整基类消息授权方法，保留其他渠道现有语义。第二批完成 NapCat 配置、入口分流、执行前授权、普通发送、界面和使用文档。这两批分别形成完整提交，完成后再按上述配置流程启用。

验收依据以下已确认的外部行为：

- 获准群中不在 `allowFrom` 的成员可以触发普通回复、自主观察、命令和已启用的群通知。
- 名单外群即使由获准用户触发，也不会进入模型处理或触发关联的媒体下载、背景查询与群发送。
- 私聊显式用户、既有通配符和已批准配对用户继续按现有规则使用。
- 新实例按新名单拒绝旧群会话和绑定群会话定时任务；跨群发送目标也必须获准。
- 空群名单没有获准群；`groupAgent.groups` 只决定获准群采用哪种回复模式。

实施时复用适用的既有检查，不默认编写或修改测试、测试脚手架，也不计算校验和。如明确要求新增或修订测试，先独立处理测试，只约束上述已确认行为，再进入实现阶段。
