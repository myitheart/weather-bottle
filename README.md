# 灵动珠 Dynamic Pearl V2.3.1 · Work Outcomes Preview

Windows 桌角挂件。光珠可展开快捷面板，短舱展示 Codex 活动和专注计时。经典天气瓶保留春、夏、秋、冬及夜空的 28 个场景。

- 点击瓶子切换天气，拖动瓶子可以摆放位置，快速横拖会晃动瓶里的天气。
- 右键菜单和托盘菜单使用同一套分类。「天气与场景」管理实时跟随、随机轮播、城市和按季节预览；「时间工具」包含专注沙漏、本地提醒和下班日落；「桌面设置」包含大小、置顶和退出。收进托盘及恢复窗口可从各自的首层菜单操作。
- 每 5 分钟获取一次 Open-Meteo 当前天气。首次启动通过 ipwho.is 按网络出口估算城市，代理可能影响结果。右键「设置城市」可固定城市，「重新自动定位」可重新识别。
- 左键换景或右键选择场景后，预览持续 5 分钟。再次换景会重新计时。可随时选「立即恢复自动跟随」。
- 右键或托盘菜单可开启「自动随机轮播」，28 个场景每轮各播一次。默认每分钟换景，可在「轮播间隔」选择 5 秒、30 秒、1 分钟，或输入自定义秒数（最短 1 秒）。修改间隔后从当前场景重新计时。轮播中左键立即换景，手动选择季节场景则退出轮播并进入 5 分钟预览。收进托盘会暂停轮播，重新显示后继续。重启会记住开关和间隔。
- 悬停显示城市、温度和天气数据时间。刷新失败时保留已有天气，30 秒后重试。窗口记住位置、大小、固定城市和置顶设置，收进托盘时暂停动画并继续更新天气。

## 启动

项目目录已有 `.venv` 时，双击 `start.cmd` 即可。首次配置可在 PowerShell 中运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

## 日常使用

### 工作回顾

从光珠快捷面板、Codex 活动、专注面板或经典瓶盖中进入「工作回顾」。

- 「成果」按一个授权项目和一个自然日手动生成草稿。支持确认、编辑、标为待核实和移除，审核进度自动保存。可选的 AI 草稿在发送前提供请求预览和单次授权。使用与验收说明见 [V2.3.1 成果草稿](docs/dynamic-pearl-v2.3.1-outcomes.md)。
- 「工作记录」可选择今天、昨天或近 7 天生成回顾，展开事项和证据，打开或复制来源，以及保存人工纠正。缓存和交互说明见 [V2.3 桌角工作回顾](docs/dynamic-pearl-v2.3-phase-4.md)。

展开项目内的「读取范围」，可分别核对普通聊天和归档聊天的读取结果。重新打开面板、切换日期或恢复上次快照时，灵动珠会先核对当前项目权限与本机缓存。支持范围见 [V2.3 规则版本机验收](docs/dynamic-pearl-v2.3-wm-09.md)。

### 桌角光珠与 Codex 活动

光珠在桌角缓慢呼吸。有后台任务时，珠内会慢慢流动暖光。任务开始、结束或中断时，短舱出现约 1.5–2 秒后收回，同一阵连续变化在一个短舱里更新。待查看结果保留暖色标记，中断和失败保留珊瑚红。悬停约 0.6 秒可看实时摘要，把鼠标移入短舱可继续查看，移出后自动收起。

轻点空闲光珠打开快捷面板，有运行或待查看活动时打开 Codex 清单。按住拖动只调整位置。右键「桌面设置 → 减少动态效果」可停用珠内动画和光珠形变，保留所有提示。右键「天气与场景 → 经典天气瓶」可临时打开天气瓶。

短舱向桌角可用空间展开活动清单，原状态显示在清单首行。每条活动显示一个聊天的项目简称、标题和状态。运行中的聊天按开始时间排列，结束或中断的聊天短暂保留在清单底部。点击活动行可打开对应的 Codex 聊天。点关闭、再点珠光、按 Esc 或点击浮层外可沿原路径收起。右键「桌面设置 → 空闲时收成光珠」可切回常驻瓶体。

在本项目目录中可用已登录的 Codex CLI 做一次只读试跑：

```powershell
.\.venv\Scripts\python.exe codex_activity.py "请只回复：灵动瓶连通测试。"
```

右键「桌面设置 → Codex 活动范围」可以选择「所有本机 Codex 聊天」「仅灵动瓶项目」或「关闭状态联动」。全局模式把通知桥接合并到用户级 `~/.codex/hooks.json`，同时保留已有 Hook。若 Codex 要求审查，在设置的 Hooks 页面审查灵动瓶的三条 Hook，然后发送一条新消息。单项目模式使用项目内的 `.codex/hooks.json`。

活动记录只留在本机，包含时间、状态、会话标识和项目简名。简名优先使用 Git 仓库目录名，其他目录使用文件夹名。清单打开后向本机 Codex 查询聊天名称，名称只缓存在内存。读不到标题时显示带短编号的聊天名称。提示词、回复和完整项目路径不写入活动记录，项目简名和标题仅在主动打开清单时显示。

「本轮已结束」表示回合结束，结果在 Codex 内查看。CLI 心跳断开约 12 秒、或 Codex Hook 超过一小时没有终态时，显示状态未确认。

### 桌角活动与专注短舱

在 Codex 活动清单的某一轮旁点「挂到桌角」，短舱显示该轮的项目简称和状态。一次挂一轮。结束后显示「待查看」，并保留到用户从短舱打开原聊天、标为已查看、在同一聊天发出下一条消息，或主动取消挂住，重启灵动瓶也可以接回。点击短舱正文可在 Codex 打开原聊天，点击靠桌角的珠光可展开清单。活动标题和聊天内容不会出现在桌面短舱。

专注和休息启动时短暂显示计时，然后分别回到金色和冰蓝色光珠。悬停查看时间，点击打开计时面板，可暂停、继续、结束或切到活动列表。完成提示收回后，珠内小勾表示待处理，点开仍能休息或结束。期间 Codex 结果在珠上留待查看标记，点击珠光可查列表。同一聊天发起下一轮时，会自动清除这条聊天先前的待查看提示；只阅读时也可点活动列表中该条提示旁的「标为已查看」，无需跳转。普通待查看标记保存在运行中的灵动瓶里，挂住的回合保存在本机。关闭光珠模式可使用原来的桌面沙漏。

### V1.1 · 瓶盖快捷舱

- 天气瓶状态下轻点瓶盖，可查看本地天气、直接开始 25 分钟专注、添加本地提醒或查看下班进度。下班进度可展开查看，也能进入原有设置。
- 再点瓶盖、点击舱外、按 Esc 或点击关闭可收起。瓶身换景和拖拽沿用原操作，专注和休息时左键仍用于暂停或继续。
- 瓶盖轻抬露出暖金光，快捷舱从靠近瓶盖的一侧舒展。收起时快捷舱沿原方向缩回，瓶盖最后合上。空间不足时改用上下位置。随机轮播照常运行。
- 输入表单优先显示，到期提醒保留并在表单关闭后展示。没有表单时，到期胶囊等快捷舱收拢后接续出现。专注、休息、天气轮播与提醒的计时独立于浮层。

### 基础功能

1. **专注沙漏。** 右键瓶子或托盘图标，打开「专注沙漏」，选 25 分钟、45 分钟或自定义时长。自定义面板默认使用分钟，可切换为秒。瓶体收腰，金砂随着剩余时间减少。悬停查看数字，左键暂停或继续。
2. **休息胶囊。** 专注到点后，胶囊向屏幕内侧展开，可开始 5 分钟休息或返回天气。瓶子和托盘的「专注沙漏 → 立即休息」提供 3、5、10、15 分钟，以及按分钟或秒输入的「自定义休息」。重新选择时长会从头计时。收进托盘继续计时，恢复显示后补呈现到点状态。天气继续刷新，随机轮播在返回天气时恢复。
3. **本地提醒。** 右键瓶子或托盘图标，选择「本地提醒 → 添加提醒」，输入内容和日期时间。到点后胶囊显示提醒时间和内容，提供「完成」和「稍后 10 分钟」。可在「待处理提醒」里查看和删除。提醒保存在本机，收进托盘、休眠或退出期间到期的提醒会在瓶子重新显示时补呈现。专注与提醒同时到期时，先显示专注完成，其他提醒按时间排队。
4. **下班日落。** 默认关闭。在瓶子或托盘的「下班日落」里启用，可设置同一天的上下班时间（默认周一至周五 09:00–18:00）。工作时段内，瓶底细金线显示进度，悬停或打开菜单可看剩余时间。瓶子可见且空闲时，下班到点会在瓶外播放约 10 秒的金色烟花，瓶内显示「下班啦」。实时天气和随机轮播照常运行，专注、休息和本地提醒优先。

当前版本完成第 1 至 4 步。专注和休息会在应用退出时结束。

### 循环提醒

在「时间工具 → 本地提醒 → 添加提醒」中选择「循环」，可选 10、20、30、60 分钟，也可输入 1 至 1440 分钟。保存后经过一个间隔首次提醒。「完成」会安排原定节奏中的下一次提醒。「稍后 10 分钟」会推迟当前提示；错过的轮次合并成一条，处理后继续循环。要结束循环，在「待处理提醒」里打开对应条目并选择「停止循环并删除」。

## V2.2.2 字体与排版

- 英文及数字优先使用 Segoe UI Variable，其次是 Segoe UI。简体中文优先使用项目随附的 Noto Sans SC 可变字体，项目资源不可用时查找系统 Noto Sans SC、Noto Sans CJK SC、Microsoft YaHei UI、Microsoft YaHei，最后使用系统默认字体。
- 随附字体只通过 Qt 注册到当前进程。原始字体和版权许可位于 [assets/fonts](assets/fonts)，取自 [Google Fonts 固定提交 7af0d90](https://github.com/google/fonts/tree/7af0d90b4d532ffa4b041937b560c6df4e7b1e95/ofl/notosanssc)，许可为 [SIL OFL 1.1](assets/fonts/OFL.txt)。
- 字体定稿为面板标题 16px / 600，短舱主状态 13px / 600，短舱计时 13px / 500，活动行标题与快捷按钮 13px / 500，活动说明及运行状态 12px / 400，活动计时 12px / 500。
- 标准控件和自绘使用同一 Qt 字体顺序。统一按实际文字宽度省略并对齐设备像素基线，计时使用 OpenType 等宽数字，缺少特性时为自绘计时按固定位宽绘制。
- 这套字体参数已冻结，后续只在明确的显示缺陷出现时调整。

本轮定稿文件为 typography.py、glass_dialog.py、reminders.py、workday.py、README.md，以及 assets/fonts/NotoSansSC-VF.ttf 和 assets/fonts/OFL.txt。

## V2.2.1 珠光与材质

- 原 512 × 512 珠光素材保留。空闲由 6.4 秒冷光呼吸与柔和底部反射表达，活跃状态以约 9.6 秒的暖光游走配合裁剪在珠内的漫射光，光核运动不会改变窗口位置。
- 短舱保留原动画时长。回收时图标先淡出、珠面提早显现，最后一段固定珠心并渐退短舱底色和边缘。
- 浅色短舱的渐变填充 Alpha 为 207、224、202，顶部细亮边和底部冷蓝反射集中在轮廓。文字与状态色继续沿用原主题。动态纹理由同一个视觉时钟采样，暖光纹理独立缓存。

## V2.2 环境动效

- ambient_orb.py 处理事件合并、优先级、展开时限、悬停与离开宽限。Codex 记录、专注时钟和本地提醒仍由原模块维护。
- activity_visual.py 在原珠光图上裁剪绘制呼吸、高光与色温不同的流光。app.py 负责在低频静置、活动流光和短时形变之间切换，并在托盘中停止绘制。
- activity_panel.py 原有玻璃浮层复用为详细计时入口。固定短舱、主动面板和到点提醒优先于短时事件，未处理状态可从珠光再次打开。

## V2.1 视觉精修

- 保留 V2.0 珠光源图。按设备像素对预乘透明图预缩放并缓存，悬停高光、底部反射和状态标记由程序绘制。
- 「桌面设置 → 挂件大小」同时作用于光珠、短舱和经典形态。保留既有设置值和桌角锚点。
- 短舱从珠体边缘延展，反射沿展开方向过渡。短舱收回时，辅助文字先淡出。快捷及活动面板先稳定玻璃轮廓，再显示内容。
- 改动文件包含 pearl_style.py、activity_visual.py、activity_panel.py、app.py、glass_dialog.py、menu.py 和 README.md。深浅色继续由程序合成，可用的视觉层次包括半透明填充、内反光和静态细纹理。

## V2.0 外观与素材

- 右键「桌面设置 → 外观」可以跟随系统主题、切换浅色毛玻璃或深色毛玻璃，设置保存在本机。
- pearl_style.py 集中管理颜色、间距、字体、动画时间、线性图标、透明帧和 QPainter 玻璃材质。描边、静态纹理和透明渐变按短舱、浮层、弹窗和控件的使用方式调整。
- assets/pearl/glass-pearl-v2.png 是用内置 ImageGen 制作的 512 × 512 透明珠光素材。QPainter 缓存本体，并实时渲染悬停高光、按下反馈、待查看标记、短舱和文字。素材由 Qt 裁整透明边缘并降采样。
- 延续 Windows 分层透明窗口。深浅外观根据系统主题或用户选择决定。玻璃使用合成渐变与细纹理，以保持动画期间透明轮廓稳定。

### V2.0 改动文件

| 文件 | 职责 |
| --- | --- |
| [pearl_style.py](pearl_style.py) | 深浅主题、设计令牌、通用材质、图标及透明快照 |
| [activity_visual.py](activity_visual.py) · [activity_panel.py](activity_panel.py) | 光珠与短舱、四项快捷操作、活动清单、空状态与过渡 |
| [app.py](app.py) | 外观持久化、交互路由、城市入口及状态呈现 |
| [glass_dialog.py](glass_dialog.py) · [menu.py](menu.py) | 玻璃弹窗、通用控件、城市搜索和统一右键与托盘菜单 |
| [reminders.py](reminders.py) · [workday.py](workday.py) | 日历、时间选择、提醒和下班设置样式 |
| [focus_visual.py](focus_visual.py) · [hourglass.py](hourglass.py) | 到点提醒胶囊、经典沙漏与流沙视觉 |
| [hover_card.py](hover_card.py) · [quick_panel.py](quick_panel.py) | 经典天气周边浮层、长项目名称提示与瓶盖面板 |
| [glass-pearl-v2.png](assets/pearl/glass-pearl-v2.png) | 透明珠光素材 |
| [README.md](README.md) | 运行方式、使用说明、素材提示词与文件清单 |

### ImageGen 素材提示词

> Use case: product-mockup. Create one isolated transparent PNG product UI asset for Dynamic Pearl, a tiny Windows desktop widget. Use the attached concept board solely as reference for the single luminous glass pearl at the upper right and its blue interior with champagne base. Render a perfect spherical premium clear pearlescent glass orb, front-on, dominant bright soft white-blue diagonal specular at upper left, faint cool smoky navy and desaturated slate blue refraction in the center, warm restrained champagne-gold internal caustic in the very bottom third, clean subtly luminous thin edge. Refined optically realistic 3D product icon, clearly readable at 28 pixels in both dark and bright surroundings. Center the sphere and make it occupy about 80% of a square canvas with generous even margin. True transparent background, crisp circular alpha edge, no floor, no cast shadow, no outer aura, no backdrop, no lettering, no other objects, no UI mockup. Deliver just the PNG isolated object.

## 视觉渲染

PySide6 透明工具窗口使用 QPainter 合成。场景由天空、云、缓存地形、水面和树木组成，动态粒子限制在瓶身内。玻璃前后层与云素材按有效 DPI 缓存，可见时以约 30 FPS 更新，换景约 0.8 秒淡入淡出。

- `renderer.py` 管理瓶身裁剪、玻璃外壳、天空与动画合成。
- `landscape.py` 绘制地形、水域、树林和云的程序化素材。
- `scenes.py` 保留天气和季节定义。
- `menu.py` 使用 Qt 的菜单交互，提供带圆角和线性图标的半透明浅色面板。
- `hourglass.py` 管理专注沙漏的玻璃、金砂和轮廓插值。稳定形态下按 DPI 缓存玻璃和沙粒纹理。
- `focus_visual.py` 绘制专注完成胶囊及展开、收回过渡。胶囊显示时保持前台窗口的输入焦点。
- `glass_dialog.py` 提供靠近瓶体弹出的玻璃面板、文本和数字输入、操作按钮、快捷选项和过渡动画。轮播间隔与专注时长复用这些组件。
