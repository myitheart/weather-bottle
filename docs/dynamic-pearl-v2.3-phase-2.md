# Dynamic Pearl V2.3 · Phase 2 事项与证据

离线原型现可按事项显示跨聊天活动、证据和下一步线索。`--work-items` 在用户指定的本机工作目录内读取所选时段的条目。规则提取在本机运行。现有活动列表仍可用，界面与实时联动无需调整。

## 生成与查看

在灵动珠仓库根目录运行。可用 `today`、`yesterday` 或 `last-7-days`，可重复传入 `--project`。

```powershell
$project = (Get-Location).Path
.\.venv\Scripts\python.exe -B -m work_memory review --project $project --range last-7-days --work-items
```

若希望以后自动识别同一事项，在每条相关聊天的用户消息里用独立一行写明确标识，例如 `事项：BILL-19`、`工单：BILL-19`，或 `Issue: https://github.com/org/repo/issues/19`。同一标识的回合可在同一个精确工作目录内跨聊天归并。完整工单链接保留主机与项目路径，查询参数和片段不保留。普通正文中的编号、引用、代码块和助手回复不决定事项身份。

- 一轮出现多个明确标识，或条目读取不完整时，保留独立回合。相同聊天标题只生成供人工核对的候选。不同工作目录各自保留事项。
- 文本视图显示事项 ID、回合锚点、里程碑和部分证据。用 `--format json` 查看标识来源、全部证据 ID、聊天/回合/条目引用，以及候选理由。
- 自动归并按回合粒度运行。一轮里面混合多个工作目标时可以保留整轮或手动调整这轮的分组，当前不能切分一条消息内部的工作片段。

## 人工纠正

显式指定本地 SQLite 后，先为要纠正的项目保存一份单项目事项回顾。`correct` 使用与该快照相同的 `--project` 和 `--range`。将下面的 `$keep`、`$other` 换成报告里的事项 ID，`$anchor` 换成要移动或确认的回合锚点。

```powershell
$db = Join-Path $env:LOCALAPPDATA 'DynamicPearl-WorkMemory-Prototype.sqlite3'
.\.venv\Scripts\python.exe -B -m work_memory --db $db review --project $project --range last-7-days --work-items
.\.venv\Scripts\python.exe -B -m work_memory --db $db correct --project $project --range last-7-days merge --into $keep --from $other
.\.venv\Scripts\python.exe -B -m work_memory --db $db correct --project $project --range last-7-days split --item $keep --anchor $anchor --title '单独核对'
.\.venv\Scripts\python.exe -B -m work_memory --db $db correct --project $project --range last-7-days confirm --anchor $anchor --milestone test --outcome success --scope 'build-42 / 本地订单回归'
.\.venv\Scripts\python.exe -B -m work_memory --db $db cached --project $project --range last-7-days --work-items
```

`correct --project $project history` 查看审计记录。`undo` 按该项目的写入顺序撤回最近一次未撤回操作。拆合关联当前快照列出的回合锚点，重新生成时优先重放人工选择。已归并的来源 ID 在仍能唯一指向一个分组时出现在 JSON 的 `aliases`。排除目录会阻止进一步读取和纠正，清除项目缓存也会清除该项目的纠正记录。

## 证据和业务状态

| 等级 | 本阶段的具体用法 |
| --- | --- |
| `Verified` | App Server 记录的回合时点、命令执行事实和结构化补丁变更。命令退出码反映进程结果。补丁条目支持修改事实。 |
| `UserConfirmed` | 用户指定来源回合、里程碑、结果和适用范围。相同范围以最新确认作为当前状态，早期确认仍可追溯。不同版本或环境分别呈现。 |
| `Reported` | 符合有限规则的助手明确声明，例如「本地测试通过」或「已发布 Beta」。未明确范围的相互冲突声明并列，显示冲突。明确写出的下一步或阻塞可提取为线索。 |
| `Inferred` | 同标题的待人工核对候选。 |
| `Unknown` | 缺少时间或可靠里程碑记录。 |

测试、提交、推送、Beta 部署和验收的自动验证需要能绑定测试集、版本或环境的独立记录。此阶段保留这些状态的报告与用户确认，并把结构化命令或补丁记录单独展示。续接线索保留明确来源，有限词表之外的行动不生成。范围不明的线索留待人工核对，避免用另一版本的结果自动标为解决。

Phase 1 数据库可事务升级到版本 2，原活动缓存继续使用原有键。事项缓存保存来源 ID、明确标识和规范化证据，完整聊天正文、命令和补丁正文均不落库。未显式指定 `--db` 时只生成当前回顾。旧快照可主动查看，新回顾以本次能读取的来源为准。

## 验证

2026-11-19 在灵动珠项目运行近 7 天事项回顾。公开 App Server 完整读取 3 条聊天，生成 6 个独立事项。85 条证据均有回合定位，包括命令、补丁和回合事件。业务里程碑自动核实为 0。真实样本没有满足规则的相同事项标识，跨聊天命中、同标题负例、多标识冲突和跨项目隔离以中文夹具验收，当前没有实测归并准确率。

共 25 项自动测试，覆盖跨聊天归并及负例、分组隔离、部分条目读取、声明冲突、正文丢弃、补丁分级、拆合重放、多个环境分别确认、撤销和旧数据库升级。

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tools -p 'test_work_memory*.py' -v
```

下一阶段的 AI 若启用，应消费结构化事项与证据，并继续沿用项目授权、证据引用和人工纠正。真实归档、Windows 端到端回跳及外部发布或验收来源仍按 [Phase 1 的覆盖边界](dynamic-pearl-v2.3-phase-1.md) 处理。
