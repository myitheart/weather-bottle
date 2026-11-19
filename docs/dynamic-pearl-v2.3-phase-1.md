# Dynamic Pearl V2.3 · Phase 1 离线活动回顾

Phase 1 提供独立的命令行原型。它读取明确选择的本机 Codex 工作目录，按项目列出回合事件、时间和来源。默认使用内存，指定 `--db` 时才维护本机 SQLite 缓存。原型沿用 Phase 0 验证过的 `vscode` 与 `exec` 来源。

## 运行方式

在灵动珠仓库根目录运行。把 `--project` 换成实际授权的绝对工作目录。可重复指定，每个目录独立查询。

```powershell
$project = (Get-Location).Path
.\.venv\Scripts\python.exe -B -m work_memory review --project $project --range today
.\.venv\Scripts\python.exe -B -m work_memory review --project $project --range yesterday
.\.venv\Scripts\python.exe -B -m work_memory review --project $project --range last-7-days --format json
```

- `--commands` 额外读取重叠回合里的命令条目，只展示时点与退出码。退出码仅表示进程结果。测试是否通过、代码是否提交、是否发布或验收仍待对应证据。
- 来源附聊天 ID、回合 ID 和 `codex://threads/<id>`。JSON 中的命令事件另附条目 ID。来源链接打开聊天级位置，Windows 端到端回跳和回合内跳转仍待验收。
- 「今天」和「近 7 天」截止于本次开始生成的时刻。跨午夜时回合开始和结束可以落在不同日期。没有可信时间的记录放在「时间待确认」，不计入已定位事件。聊天标题仅作为显示标签，聊天创建时间和更新时间均不代替回合时间。
- 普通和归档分别查询，归档正例覆盖仍待实测。原型扫描指定的精确 `cwd`，不会自动寻找子目录、工作树或其他存储。只读发现以当前 Codex 本机索引为边界。
- 当页数、响应字节或时间超限，或接口不支持时，已读取的事件仍可展示，结果标「部分读取」。`--list-pages`、`--turn-pages` 和 `--item-pages` 可调整页预算。读取中按 `Ctrl+C` 取消。在支持条件内读完且没有事件时显示「本次查询无活动」。退出码 `0` 表示读取结束或读到缓存，`1` 表示来源不可用，`2` 表示用法或数据库错误，`3` 表示部分读取，`130` 表示取消。

### 本地缓存与项目排除

以下 `--db` 放在子命令前。示例库为原型单独使用，可换成其他显式选择的文件。用相同范围、项目与 `--commands` 标记读取缓存。

```powershell
$db = Join-Path $env:LOCALAPPDATA 'DynamicPearl-WorkMemory-Prototype.sqlite3'
.\.venv\Scripts\python.exe -B -m work_memory --db $db review --project $project --range last-7-days
.\.venv\Scripts\python.exe -B -m work_memory --db $db cached --project $project --range last-7-days
.\.venv\Scripts\python.exe -B -m work_memory --db $db exclude --project $project
.\.venv\Scripts\python.exe -B -m work_memory --db $db include --project $project
.\.venv\Scripts\python.exe -B -m work_memory --db $db clear --project $project --yes
```

完整结果按本机 Codex 数据目录、日历范围和项目集合更新对应快照。相同会话、回合与条目重复读取时更新观察记录。部分读取和取消保留上次完整快照，缓存仅由 `cached` 主动查看，始终标明生成时间。数据库保存规范化字段、聊天名称、来源定位和回顾快照。提示词、回复、命令正文和命令输出均不落库。原型当前由用户主动清理，尚未自动过期。`clear --all --yes` 清除该库的全部回顾数据，保留排除偏好，只作用于原型自己的 SQLite 文件。

## 验证结果

本机验证日期为 2026-11-19（北京时间）。使用 Phase 0 的两个授权项目，公开 App Server 分别完成 3 条和 103 条普通聊天的元数据及回合扫描。三个日期范围均成功生成。两项目的归档查询返回空，因此真实归档覆盖仍待验收。

| 校验 | 实测结果 |
| --- | --- |
| 日期与来源 | 同 Phase 0 的 3 条跨日聊天共 53 个回合。对区间内事件逐条核对 `(聊天 ID, 回合 ID, 毫秒时间)`，今天 13 起、13 止，昨天 3 起、3 止，近 7 天 47 起、47 止，三个集合均与桌面连接一致。 |
| 命令活动 | 灵动珠项目的今天回顾中读到 37 条命令结束事件。每条都有聊天和回合定位，展示的是退出码或其缺失状态。 |
| 部分读取 | 用第二个项目将列表预算限制为 1 页。保留已读活动，返回 `partial` 和 `ordinary:page_budget`，进程退出码为 3。 |
| 持久化 | 用隔离的临时数据库连续生成同一范围，快照只保留 1 份。独立进程读取缓存，随后核对了排除、恢复纳入与全量清除。真实历史的其他验证使用内存数据库。 |
| 回归 | 共 18 项通过，含真实接口之外的匿名夹具测试。覆盖午夜、23 小时自然日、缺失时间、分页重叠、无数据、旧接口错误、超时、取消、越界回合读取防护、晚到结束事件、并发清理和覆盖不完整时保留缓存。 |

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tools -p 'test_work_memory*.py' -v
```

原型复用了 [Phase 0](dynamic-pearl-v2.3-phase-0.md) 的只读传输和分页逻辑。历史版本、新增变更的索引时效和真实归档等兼容性结论仍按 Phase 0 的边界执行。每次从头做有界扫描，当前没有基于 `updatedAt` 的提前停止。Phase 2 可以在这些结构化活动与来源上建立跨会话事项、纠错和更严格的证据判定。现有灵动珠 UI、实时 Codex 联动和 Hook 保持原来的运行入口。
