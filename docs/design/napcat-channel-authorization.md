# NapCat 群聊与私聊授权分离方案

本文提出待实施的授权调整。目标是群聊仅按 `allowGroups` 授权，获准群内任意成员都可参与；私聊入站继续使用 `allowFrom` 和已有配对授权。群范围必须同时约束输入、模型执行和群动作出口。以下新增字段、授权 hook 和检查均属于设计方案，现有代码尚未实现。

## 当前行为与问题来源

当前 [`NapcatConfig`](../../nanobot/channels/napcat/runtime.py) 只有 `allow_from`，没有独立群准入名单。`_on_message` 先检查 `GroupObserver.enabled(group_id)`，自主群进入 `_observe_group`，其余群仍按 `groupPolicy` 处理。普通路径先下载图片，再调用 `BaseChannel._handle_message` 按用户授权；自主路径也通过 `is_allowed(sender_id)` 筛选参与者。因此，`groupAgent.groups` 表示自主回复模式的适用群，无法表达“仅在这些群中运行”。

[`BaseChannel.is_allowed`](../../nanobot/channels/base.py) 的实际用户语义是：`["*"]` 放行全部用户，显式名单放行对应用户，随后查询配对授权，最终拒绝。显式名单并不会禁用已存在的配对授权；空名单表示仅允许配对已批准的用户。当前 NapCat 调用 `_handle_message` 时没有传入 `is_dm=True`，因此不能将“保留配对已批准用户可用”误写成“NapCat 已经自动发送配对码”。

当前 [`NapcatChannel.send` 和 `_group_action`](../../nanobot/channels/napcat/runtime.py) 都没有群准入判断。前者承接普通回复与渠道发送，后者承接自主群动作并直接调用 OneBot API；只修改普通消息入口或普通发送入口，都无法覆盖完整能力范围。

## 授权契约

拟新增 `channels.napcat.allowGroups`，保持 `allowFrom` 的用户字段形状。两者分别服务于不同聊天场景，不作并集或交集运算。

| 场景或配置 | 拟采用的行为 |
| --- | --- |
| 群聊入站 | 仅检查群号是否通过 `allowGroups`；群成员不再经过 `allowFrom` 过滤 |
| 私聊入站 | 检查 `allowFrom`，并保留原有已批准配对用户语义 |
| `allowGroups` 缺省或 `[]` | 拒绝全部群聊 |
| `allowGroups: ["*"]` | 允许全部群聊，不改变私聊权限 |
| `allowFrom` 缺省或 `[]` | 私聊仅允许已有配对授权的用户，不影响获准群内成员 |
| `allowFrom: ["*"]` | 允许任意用户私聊；仍不能越过群准入名单 |
| 群聊出站 | 目标群必须通过 `allowGroups` |
| 私聊出站 | 保留现有发送行为；本方案不将 `allowFrom` 扩展为私聊发送目标名单 |

获准群再根据 `groupAgent.groups` 选择自主合批模式，其他获准群继续使用 `groupPolicy`。群准入判断必须先于模式选择；两个群列表不互相推断或自动合并。现有模式选择与字段定义见 [`group_agent.py`](../../nanobot/channels/napcat/group_agent.py)、[`runtime.py`](../../nanobot/channels/napcat/runtime.py) 和 [`manifest.py`](../../nanobot/channels/napcat/manifest.py)。

私聊出站保留原行为，是为了避免这次群授权调整悄然改变跨目的地 `message` 工具的既有权限。该工具在自主群中的别名仍允许其他目的地走原始工具，见 [`GroupMessageAlias`](../../nanobot/channels/napcat/group_tools.py)。如果未来需要限制私聊收发双方，应单独定义契约与迁移方式。

## 统一授权上下文

建议在 [`BaseChannel`](../../nanobot/channels/base.py) 增加一个纯同步 hook，例如 `is_message_allowed(sender_id, chat_id, authorization_id=None)`。默认实现按原规则选择 `authorization_id` 或 `sender_id`，再调用 `is_allowed`；`_handle_message` 改为调用该 hook。这样其他渠道现有用户授权和 `authorization_id` 语义保持一致，消息构造、流式标记、配对回复和总线发布继续由基类负责。

NapCat 覆写这个上下文 hook：`group:<id>` 只调用频道自己的群授权判断，`private:<id>` 使用原用户授权路径。`is_allowed` 继续表示用户是否获准，不承担群判断。真实 `sender_id` 始终保留在 `InboundMessage` 中，供模型、日志和引用使用。

不建议将裸群号传给 `authorization_id`：基类会把它当用户查询配对，群号与用户号相同就可能误授权。也不建议用 `group:` 字符串前缀覆写 `is_allowed`：当前 OneBot 入站边界没有统一约束 `user_id` 类型，外部字符串可能与内部编码的授权主体混淆。显式传递聊天上下文可以避免这类类型混淆，也无需复制 `_handle_message` 的消息组装逻辑。相关事实见 [`BaseChannel._handle_message`](../../nanobot/channels/base.py)、[`NapcatChannel._on_message`](../../nanobot/channels/napcat/runtime.py) 和 [`pairing/store.py`](../../nanobot/pairing/store.py)。

## 输入与合批边界

`_on_message` 应先解析聊天类型、目标和发送者，再执行对应授权。拒绝群消息时不继续进行图片下载、引用目标查询、消息背景查询、命令派发或观察器入队；私聊拒绝时同样避免先下载媒体，同时保留现有用户和配对处理行为。自主群的群成员不再按 `allowFrom` 筛选。当前普通媒体下载和自主引用查询分别位于 [`_on_message` 与 `_observe_group`](../../nanobot/channels/napcat/runtime.py)。

`_on_notice` 应在群成员查询之前检查群授权，统一覆盖戳机器人、入群欢迎等群通知。机器人自己的群消息仍可作为获准自主群的背景输入，但不能绕过群范围。普通群命令和自主群命令都在授权之后交给现有 Gateway 命令分发，不新增独立命令权限体系。相关入口见 [`runtime.py`](../../nanobot/channels/napcat/runtime.py)。

观察器的延迟提交也应使用同一群授权判断，在准备媒体与背景之前以及最终发布之前确认群仍获准。建议给 [`GroupObserver`](../../nanobot/channels/napcat/group_agent.py) 提供明确的群准入回调，使 `enabled` 和 `flush` 使用频道拥有的判断，避免观察器自己复制另一份名单。撤权时丢弃该群未发布批次，不将拒绝降级为普通会话输入。

现有 `NapcatChannel.stop` 已取消背景任务并调用 `GroupObserver.close`，后者取消计时器、清空内存批次。正常禁用会清理这部分等待输入，但不能据此宣称所有已运行模型任务和定时任务都已取消；这些任务还需要下面的执行和出口检查。实现依据见 [`runtime.py`](../../nanobot/channels/napcat/runtime.py) 与 [`group_agent.py`](../../nanobot/channels/napcat/group_agent.py)。

## 已有会话、定时任务与渠道停用

建议 `NapcatChannel.turn_policy` 对所有属于该渠道的群会话先检查当前群准入，再决定是否注入自主群工具。未获准必须明确拒绝执行，不能返回 `None`，否则会回到普通执行路径。现有 [`AgentLoop`](../../nanobot/agent/loop.py) 在模型请求准备前调用渠道策略提供者，这个位置可以阻断已有群会话和恢复任务的新一轮模型调用。绑定会话的 [`cron/bound_runner.py`](../../nanobot/cron/bound_runner.py) 也沿用会话路由提交任务，拒绝应记录为确定的执行失败。

执行前检查应按目标会话类型分流，本次新增准入限制针对群目标；私聊入站由上下文 hook 保持原语义，私聊历史与定时执行暂不另加用户授权限制。如果以后扩展私聊执行前检查，应使用目标私聊的 QQ 用户身份查询原用户授权，不能把定时任务的 `cron` 或系统触发的 `system` 发送者标签当作实际私聊用户。当前定时输入的发送者形状见 [`cron/bound_runner.py`](../../nanobot/cron/bound_runner.py)。

当前 [`ChannelManager.turn_policy`](../../nanobot/channels/manager.py) 找不到运行实例时直接返回 `None`，而停用操作会移除实例。因此仅在 NapCat 实例内增加拒绝，仍会遗漏停用渠道后的旧会话和定时任务。推荐同时在 ChannelManager 的执行策略分发入口增加通用检查：如果路由属于已配置的外部渠道实例，但实例未运行或正在停用，则在调用模型前拒绝；该检查应覆盖停用、启动失败和依赖加载失败。

配置归属应由无运行依赖的渠道描述及实例契约识别：遍历实际存在的渠道配置节，用 [`channel_instance_specs(..., enabled_only=False)` 和 `channel_runtime_name`](../../nanobot/channels/contracts.py) 建立配置实例与运行名的映射，再与当前运行集合及停止集合比较。不能只复用当前启用实例表，也不能按任意会话前缀猜测其归属。显式的 `cli`、`system` 以及未配置但合法的内部或直接执行路由应保留原行为；默认启用渠道和多实例运行名应按原描述契约处理，避免因停用防护误伤合法调用。当前初始化与停用逻辑见 [`ChannelManager`](../../nanobot/channels/manager.py)。

这一通用检查需要独立验收配置实例解析和合法路由兼容性，再与 NapCat 授权一并交付。它限制后续执行准入，不承诺撤销已经提交给提供商的模型请求。已获工具的运行任务仍必须受到群出口检查约束。

## 群发送与直接动作出口

`send` 应先验证地址和目标群授权，再判断是否连接、是否抑制自主群普通正文、是否处理媒体。拒绝使用确定的 `DeliveryRejectedError`，使普通回复、进度、错误、恢复通知、定时结果和 `message` 工具投递共享边界。现有 [`ChannelManager`](../../nanobot/channels/manager.py) 会将该错误记为拒绝发送，而不会作为未知投递结果盲目重试。

自主群工具直接使用 OneBot API，因此还应把当前 `GroupRun.group_id` 显式绑定到频道动作调用器，在 `_group_action` 调用 `_call_action` 之前检查。不能仅从动作参数读取 `group_id`：表情回应和按 ID 读取消息的调用没有这个字段。绑定上下文可以统一覆盖发送、戳一戳、表情回应、消息读取和历史查询，确保已经建立的工具运行也会在撤权后被拒绝。对于携带 `group_id` 的动作，同时保持它与绑定群一致。现有动作形状见 [`GroupRun` 与 `QQGroupTool`](../../nanobot/channels/napcat/group_tools.py)。

拒绝必须发生在表示投递未知的异常转换之前，避免把“确定没有提交的权限拒绝”错误标成“可能已发送”。建议频道提供单一群准入判断及对应的确定拒绝 helper，在真实能力边界复用，而不为每个读取函数叠加独立名单或 fallback。

直接动作调用器还不覆盖所有旁路：`_enrich_group_message` 和 `_transcribe_group_voice` 直接使用 `_call_action`，`GroupRun.send` 的媒体转换也发生在 `run.call` 之前。它们应在背景补充、语音获取和附件处理开始前复用群准入检查；转写回调、背景回调和媒体回调应携带当前群上下文。这样名单外群不会先获取数据或处理媒体，随后才在发送时失败。相关路径见 [`runtime.py`](../../nanobot/channels/napcat/runtime.py) 与 [`GroupRun.send`](../../nanobot/channels/napcat/group_tools.py)。

## 配置、界面与迁移

拟在 [`NapcatConfig`](../../nanobot/channels/napcat/runtime.py) 增加 `allow_groups: list[str]`，默认空列表；在 [`manifest.py`](../../nanobot/channels/napcat/manifest.py) 登记 `allowGroups`，在 [`webui/index.ts`](../../nanobot/channels/napcat/webui/index.ts) 将它与私聊授权字段放在访问配置区。中文标签建议分别为“允许群聊”和“私聊用户”，说明文字写清空名单、通配符及配对含义；所有现有 [渠道语言包](../../nanobot/channels/napcat/webui/locales/) 同步维护。`groupAgent.groups` 继续表示“自主回复群号”，不更名为授权名单。

这是有意收紧群范围的兼容性变更。旧配置缺少 `allowGroups` 时，群输入和群输出都将拒绝；需要明确填入获准群号，或主动选择 `["*"]`。不从 `groupAgent.groups` 自动迁移，不把旧 `allowFrom` 推断成群名单，也不修改既有配对记录。应同步更新 [渠道配置指南](../chat-apps.md) 与 [自主回复设计](napcat-group-autonomous-replies.md)，给出群模式和群授权分别配置的示例。

现有频道实例保存构造时的配置对象，直接修改 JSON 不应被描述为立即撤权。群发送检查也不会终止已经运行的普通 `exec`、文件工具或已提交的模型请求。当前构造、启停与配置读取路径见 [`ChannelManager`](../../nanobot/channels/manager.py)。

本方案不新增实时授权变更与全局任务取消系统。推荐的名单收缩应用顺序是先停止 Gateway，使旧模型任务和工具停止，再修改名单，启动使用新配置的实例；如果采用通道重建，必须先明确取消关联运行，不能仅凭通道连接已关闭就视为任务已取消。新实例对恢复会话和定时任务执行前重新授权，出口检查处理新运行下的群动作。这个应用顺序属于配置契约，不应将原地修改某个旧对象的字段当作用户配置已即时生效。

## 实施分批与验收

建议分成两批提交，第一批仅增加上下文授权 hook，默认实现严格保持其他渠道现有授权行为，复用原 `_handle_message` 的组装与配对流程。该批不改变 NapCat 实际准入范围。

第二批一次完成 NapCat 的 schema、管理契约、界面语言包、场景分流、观察器检查、执行策略、普通发送与直接 API 出口，以及通用已配置停用渠道执行防护和配置迁移文档。输入和输出是同一个安全契约，不拆成中间可发布但防护不完整的批次。

验收采用离线可观察行为，不依赖连接真实 NapCat：

- 获准群中不在 `allowFrom` 的成员可进入普通、自主、命令和通知路径；名单外群即使发送者显式获准、配对获准或 `allowFrom=["*"]`，也不产生总线消息、媒体下载或背景 API 请求。
- 群号恰好等于某个配对用户号时仍不获准；缺省、空名单和显式通配符分别符合配置契约；私聊显式用户、通配符和已有配对继续符合原语义。
- 普通发送、进度、错误、工具动作和恢复投递到未获准群时确定拒绝，连接和媒体转换均未发生；私聊出站保持现有行为。
- 已创建的群运行在它所使用的有效配置中被撤权后，发送、戳一戳、表情、查询和语音获取均不能提交 OneBot 请求；附件转换、背景补充和等待批次也不继续处理。通过上述停止与应用流程验证旧运行已结束，新运行使用新名单。
- 现有群会话与绑定 cron 在模型调用之前被拒绝；已配置但未运行渠道、启动失败渠道、多实例停用均受控，`cli`、`system` 和合法未配置路由继续可用。

现有可复用测试入口包括 [NapCat 渠道测试](../../nanobot/channels/napcat/tests/test_napcat_channel.py)、[群合批测试](../../nanobot/channels/napcat/tests/test_group_agent.py) 和 [媒体与事件测试](../../nanobot/channels/napcat/tests/test_group_media_and_events.py)。通用 hook 与 ChannelManager 路由防护应在各自已有测试集中验证其对其他渠道和合法执行路由的兼容性。
