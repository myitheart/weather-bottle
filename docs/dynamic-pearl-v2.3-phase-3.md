# Dynamic Pearl V2.3 · Phase 3 可选 AI 回顾

Phase 3 在本机规则回顾上增加可选的证据选读和核对顺序。沿用 Phase 2 的事项、状态和人工纠正。模型可以选择现有证据、续接线索或归并候选，应用根据本机原记录生成文字与来源链接。

## 使用方式

默认的 `review --work-items` 继续离线。以下命令只在本机生成预览。`$model` 由用户选定，需支持 OpenAI Responses API 的 Structured Outputs。

```powershell
$project = (Get-Location).Path
$model = '替换为你选定的模型 ID'
.\.venv\Scripts\python.exe -B -m work_memory review --project $project --range last-7-days --ai-model $model --ai-preview
```

用户需要使用自己的 OpenAI API 凭据，通过环境变量 `OPENAI_API_KEY` 提供。在交互终端中去掉 `--ai-preview` 后，每个项目都会显示日期范围、模型、接收方、预算、数据政策及完整的拟发送 JSON。输入当前预览指定的「发送 + 校验码」才授权此项目的请求或缓存复用。直接回车跳过。非交互输入或重定向标准错误时只有预览。`--format json` 时正式回顾写入标准输出，预览写入标准错误。

接收方固定为 `https://api.openai.com/v1/responses`。请求设置 `store:false` 并关闭重定向。实际数据保留适用账户和组织的 API 数据政策。Codex 桌面登录与此凭据独立。 [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create) · [OpenAI 数据控制](https://developers.openai.com/api/docs/guides/your-data)

## 发送边界与结果校验

- 每次请求只处理一个授权项目。以固定字段白名单生成匿名编号、证据等级、事件类别和里程碑类别。聊天文字、标题、工单标识、路径、精确时间、项目名称、用户确认范围、命令正文及输出均不进入模型请求。API 密钥只用于该接收方的授权头。
- 模型输出用严格 JSON Schema 限制为证据编号和候选编号。客户端还校验证据归属、候选两端引用、续接线索类型和数量限制。返回正文、工具调用、拒绝、截断或无效引用时回到规则结果。 [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- 证据选读的正文、等级和跳转链接使用本机引用。模型只能筛选由 Phase 2 提供的弱归并候选，候选仍需人工处理。没有可靠证据的业务里程碑仍显示待核实。只排序已有续接线索。
- 目前用实际请求体字节限制体量。单次最多 4,000 字节，每轮累计最多 20,000 字节，包含重试。每个请求设置最多 600 个输出 token，成功后显示或输出 API 返回的 token 用量。预算内的短限流最多重试一次；网络结果不明时回退离线，避免重复请求。字节预算是工程上限，费用和模型 token 数依实际 API 用量。
- 每个项目按顺序选取至多 12 个事项，每项至多 5 个证据，优先保留报告、有效确认和待办线索。预算外或读取不完整的项目仍保留本机规则回顾。

## 本地缓存与撤回

指定 `--db` 后，已验证的匿名选择可缓存，独立于规则快照。缓存关联项目、Codex 来源、日期、模型、提示词及来源证据。复用缓存仍须在当前预览中明确授权。未指定 `--db` 时只用内存；旧版原型数据库可事务升级到版本 3。SQLite 保存的是通过校验的选择编号，没有 API 密钥、请求正文或模型原始响应。

```powershell
$db = Join-Path $env:LOCALAPPDATA 'DynamicPearl-WorkMemory-Prototype.sqlite3'
.\.venv\Scripts\python.exe -B -m work_memory --db $db revoke-ai --project $project
```

项目排除与清除也会删除相应的 AI 缓存。预览期间撤回会阻止发送，重试前再次核对授权范围。已经提交给接收方的请求适用其数据政策。

## 验证与当前边界

开发前 Phase 2 的 25 项测试通过。完成后共 35 项通过，新测试覆盖逐项目授权、非交互默认零外发、匿名投影、凭据和提示注入隔离、固定接收方、拒绝与截断、无效编号、限流与超时、撤回和 SQLite 升级。

2026-11-19 用灵动珠项目运行真实历史的只预览流程。扫描 3 条聊天，预览纳入 7 个事项和 30 条匿名证据，请求体 3,508 字节。网络调用次数为 0。模拟模型已覆盖成功与故障路径，实际供应商调用和模型排序质量仍待用户明确授权后验证。

此阶段选择让模型排序已知证据，并由模板生成摘要。它对自由文本的语义归并能力尚未引入，适合先验证授权和证据约束。Phase 4 可以使用规则回顾完成界面集成，云端增强继续作为明确选择的模式。
