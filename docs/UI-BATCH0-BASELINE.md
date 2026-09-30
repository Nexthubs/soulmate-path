# UI 批次 0 基线记录（SP-1101）

> 状态：DONE（证据完整；限制与 NOT_RUN 见 §8）
> 日期：2026-09-30
> 代码基线：`63b2902`（工作区无应用代码改动；本任务只新增文档与证据产物）
> 输入：`docs/UI-IMPROVEMENT-EXECUTION-PLAN.md` §3（批次 0）；上下文按选择性加载协议读取 SP-102/103/104/105/207 handoff 与 DEV-SPEC §2.1、§4–6、§16。

## 1. 目的与方法

按执行计划批次 0 建立"改动前"基线：确认相关 Figma 设计节点与组件映射，并在**生产构建模式**下录制问卷关键交互（单选、日期滚轮、quiz↔transition、Transition-5→email）的屏幕录像、网络瀑布与父组件更新计数，覆盖正常网络、注入 500ms 响应延迟、请求失败三类状态。全部录制的视口为 390×844（DEV-SPEC §2.1 设计基线）。

## 2. 环境与构建

| 项 | 值 |
|---|---|
| 代码版本 | `63b2902`（`refine(quiz): widen the wheel selection band…`），工作区除本任务文档/证据外无改动 |
| 前端构建 | `next build`（Next 15.5.25）+ `next start`，NODE_ENV=production，全部 soulmate 路由静态预渲染 |
| React | 19.3.0（生产 bundle，无 StrictMode 双渲染干扰） |
| prebuild quiz JSON 同步 | `npm run build` 后 `git status` 干净——canonical JSON 已同步，无无关 diff 混入 |
| 浏览器 | ZCode 内嵌浏览器（Chromium 内核，UA `Mozilla/5.0 (Macintosh…)`，桌面级渲染），视口 390×844，DPR 1。**非真实移动设备**（见 §8） |
| 后端 | 本地 dev 后端 `127.0.0.1:8000`（共享 dev DB），真实匿名 session 走完整 API |
| 网络 | 本机回环；"注入 500ms"为代理人工注入（见 §6.2），非真实公网耗时 |

**生产配置门的处理（插桩说明，无应用代码改动）：**
生产模式下 `ConfigValidator`/`assertClientConfig` 要求 HTTPS 非 localhost 的 API 基址，否则浏览器端抛错触发 error boundary，无法录制。因此重建时以进程环境变量烘焙**生产形态**配置：`NEXT_PUBLIC_APP_BASE_URL=https://soulmate.giaogiao.work`、`NEXT_PUBLIC_API_BASE_URL=https://soulmate.giaogiao.work/api/soulmate`、`NEXT_PUBLIC_SOULMATE_INTRO_PRICE=0.10`、`NEXT_PUBLIC_SOULMATE_REGULAR_PRICE=29.90`（PayPal client id / 加速价沿用 `.env.local`）。该 URL 不会真实出网：录制代理在 document-start 把 API fetch 重写回同源代理（`docs/artifacts/ui-batch0/recording-proxy.mjs`，置于 /tmp 运行，不进应用仓库），`/api/*` 转发到本地 dev 后端，其余转发到 `next start`。除内联的环境常量外，bundle 即本树的生产构建。三项环境事实（生产构建模式、配置门行为、插桩重写）均已如实记录。

## 3. 渲染计数插桩（父组件更新次数）

React 19 生产 bundle 仍会在模块求值时调用 `__REACT_DEVTOOLS_GLOBAL_HOOK__.inject()`（已在 `react-dom-client.production.js` 19.3.0 源码与运行时双向验证），但 React 19 移除了 `PerformedWork` 标志，因此插桩改用：

- 代理向每个 HTML 文档注入 hook，`onCommitFiberRoot` 遍历 fiber 树；
- 某函数组件在该 commit 中"发生了渲染"的判据：新挂载（`alternate == null`），或 `memoizedProps`/`memoizedState` 与 alternate（双缓冲副本）引用不等；
- 组件名经 `window.__SP_TARGET_NAMES`（type 函数引用 → 标签）归因。标签在页面水合后由 DOM 标记 + hook 链判别自动建立：`[data-testid="quiz-back-button"]` 向上第 1 个函数组件 = `QuizShell`（0 hooks），再向上首个 ≥5 hooks 者 = `QuizPageContent`（实测 20 hooks）；`[role="radio"]` 向上第 1 个 = `OptionCard`；`[data-testid="dob-wheel-picker"]` 向上 = 滚轮内部组件。标签按 type 引用（而非压缩名）建立，跨渲染稳定。

聚合数据：`window.__SP_COMMITS = { total, byName, last }`；逐场景快照存 `docs/artifacts/ui-batch0/normal-run-commit-stats.json`。

## 4. Figma 节点 → 组件 → 批次 1 视觉变化 → 验收截图

经 figma-mcp-go 核对（文件 "Soulmate Path"，单页 Main Page；设计帧均为 390×884/918）：

| Figma 节点 | 名称 | 实现组件 | 批次 1 计划视觉变化（本方案 §4） | 验收截图（批次 1 需重拍对比） |
|---|---|---|---|---|
| `102:121` | 单选题 | `QuizShell` + `OptionCard(single)` | 背景扩展至全视口；390 内容几何（px-6/342px 槽）不变 | `screens/back-restore-q02.png`、`screens/failure-error-banner-q02.png`（含选中态与错误横幅） |
| `102:130` / `102:137` | 选项选中/未选态 | `OptionCard` | 不变（仅背景层变化） | 同上（Male 选中：`#5c3c4f` 边框+勾选，未选 `#ffffff99`） |
| `102:201` | 多选题 | `QuizShell` + `OptionCard(multi)` + `QuizNextButton` | 同上 | `rec-5-t5-popups-email.webm` 开头（视频帧） |
| `102:241` / `102:242` | 底部按钮区 / Next 按钮 | `QuizNextButton`（60px、r20、`#2c2c2e`） | 不变 | 同上 |
| `102:161` | "Html → Body"（旧日期下拉设计） | **已被替代**：owner-directed `WheelDatePicker`（f042de9…63b2902） | 非批次 1 目标；Figma 该帧不作为滚轮视觉依据 | `rec-2-t1-t2-wheel.webm`、`rec-6-latency-500ms.webm` |
| `102:245`/`304`/`320`/`345`/`372`/`386` | 过渡-0…5 | `TransitionShell`（+`Transition5Progress` for 386） | 背景扩展全屏，内容居中限宽不变 | `screens/normal-T0.png`、`normal-T2.png`、`normal-T3-zodiac.png`、`normal-T5-progress.png`（T1/T4 见 SP-104 证据与录屏） |
| `102:425`/`466`/`445` | 过渡-5 弹窗 1/2/3 | `InterstitialModal` / `WarningModal` | 不变 | `rec-5-t5-popups-email.webm` |
| `102:486` / `102:557` | 填邮箱 prefer 女/男 | `EmailCaptureView`（自带冷色渐变 `#fbfaff→#f7f5fb→#ffffff`） | 保留自身背景，仅全屏化 | `screens/normal-email-female.png`（q03=Female 变体，徽章 Female/20–30/Caucasian 来自 q03/q05/q06） |

已在实施前记录的现状差异（不属于本批修复范围）：Figma 测验帧背景填充为 `#ffffff`，实现为暖色渐变 `#fff0f3→#fef4e9→#fef3de`（SP-102 起的既定实现，方案默认保留）；共享壳 `src/app/soulmate/layout.tsx` `main` 为 `max-w-[390px] bg-white shadow-sm`，`FlowShellFallback`/`QuizShell`/`TransitionShell` 均再各自 `max-w-[390px]`——批次 1 的"取消公共外壳 390px 限制"即针对此结构。

## 5. 正常模式测量结果（生产构建，390×844）

### 5.1 交互与渲染计数

| 场景 | 测量 | 结果 |
|---|---|---|
| 单选点击（q02 Female） | 点击后 commit 增量与归因 | **+2 commits**；选择 commit 内渲染组件 = `QuizPageContent`、`QuizShell`、`RadioGroup`、`OptionCard`（共 49 个函数 fiber）+ Next 边界组件。即**当前整组选项随点击全量重渲染**（批次 2 的改动对象） |
| 日期滚轮（q08） | 3+2 次 `cua.scroll`（月/日/年列）+1 次点选远处行，共 ~8–9 commits | **`QuizPageContent` 更新 = 0，`QuizShell` = 0，`OptionCard` = 0**；全部 commit 落在滚轮内部组件（wheel-internal:k/m/s 各 +3/+3/+3）。`last.names` 仅含滚轮子树与 2 个常驻 minified 组件（f/o/l）。**（2026-09-30 批次 4 更正：此结论是插桩伪影——`__SP_TARGET_NAMES` 标签循环在滚轮页把 QuizPageContent 的 fiber type 重复打成了 `wheel-internal:*`，父组件每 burst 的渲染被记入错误键下。代码审读证实当时实现为每行 `onChange`→父组件重渲染；批次 4（SP-1105）已实现本地 draft+结算提交并实测修正归因。）** |
| 滚轮显示值 vs 提交值 | 显示 "April 27, 2000" → 提交后 T3 服务端星座 | **一致**：T3 显示 "Taurus Sun"（04-20~05-20 ✓，服务端计算）。批次 4 担心的"显示值≠提交值"在当前 `63b2902` 正常路径未复现 |
| 静止渲染速率 | q02 静置 800ms 采样 | 0 commits/s，无持续重渲染循环 |
| 冷启动突发 | 落地页→T0→q02（3 次软导航挂载） | 约 **3400+ commits** 累积突发（挂载期瞬时，非持续）。量级异常，建议批次 3 数据准备时复查挂载链路（不阻塞本基线） |
| 产品内 Back | q03 → Back | 服务端 `navigateBack` → q02，**答案恢复**（Male `aria-checked=true`）；`screens/back-restore-q02.png` |

### 5.2 网络路径（warm/cold）

代理日志（`failure-retry-network.jsonl` 前 6 行 + `latency-500ms-network.jsonl`）显示：

- 冷进入（新会话）：`GET /sessions/current`(403) → `POST /sessions`(201) → `GET /sessions/{id}` → `POST /transitions/.../continue` → `GET /sessions/current` + `GET /quiz/config`（quiz 页首挂载）。
- **warm 路径零重复 bootstrap**：整个正常行走（q02→…→q18、6 个过渡、q18→T5→email）及 latency 行走中，`/sessions/current` 与 `/quiz/config` 仅在冷进入出现，q→q 与 transition→quiz 均只发答案/continue 请求——批次 3 的"不重复请求 bootstrap API"当前已满足。

## 6. 三类网络状态

### 6.1 正常

浏览器侧 resource timing 39 条 API/导航条目（`normal-run-resource-timing.json`）。全程无错误横幅；T5→email 边界正常（`rec-5`）。

### 6.2 注入 500ms 响应延迟（人工注入，非公网耗时）

代理对全部 `/api/*` 响应统一 +500ms。实测 9 条 API 调用 dur 505–535ms（`latency-500ms-network.jsonl`）。观察（`rec-6-latency-500ms.webm`，467 帧）：

- 冷进入 bootstrap 为 **4 次串行 API**（current/create/session/continue），+500ms 下首题可交互前额外等待 ≈2.1s（不含 RTT）；
- 每次答案提交 +~530ms 期间**正文保持原内容**，未出现全页 skeleton 替换；选中态即时显示；
- 推进仍严格按服务端 `next_step`，无错序。

### 6.3 请求失败（网络级：连接被代理切断）

`PUT /answers/q08` 前两次均 `CONNECTION_DESTROYED`（`failure-retry-network.jsonl`，`rec-7-failure-retry.webm`，269 帧）：

- 原地错误横幅 "Failed to fetch" + Retry（`screens/failure-error-banner-q02.png`）；
- **已选选项保持完整选中视觉**（梅紫边框+勾选，非灰化）——批次 2 验收项"点击后整组选项不变灰、选中状态稳定可见"当前已成立；
- 解锁后点 Retry：同答案经服务端 upsert 接受并推进 q03（顺带再次印证答案 upsert 幂等）；
- 失败期间无跳页、无内容替换。

## 7. 证据索引（`docs/artifacts/ui-batch0/`）

| 文件 | 内容 |
|---|---|
| `rec-2-t1-t2-wheel.webm` | T1→q07→T2→q08 到达（后台录制模式仅捕获 302ms，见 §8 限制） |
| `rec-3-quiz-to-transition.webm` | 5.7s/170 帧：q09→q10→T3（quiz→transition 切换） |
| `rec-4-transition-roundtrip.webm` | 6.9s/208 帧：T3→q11→T4→q12（transition→quiz 往返） |
| `rec-5-t5-popups-email.webm` | 8.8s/263 帧：T5→三弹窗→email（T5→email 边界） |
| `rec-6-latency-500ms.webm` | 15.6s/467 帧：+500ms 下落地→T0→q02…q04 |
| `rec-7-failure-retry.webm` | 9.0s/269 帧：PUT 失败→错误横幅→重试点击 |
| `screens/*.png`（7 张） | T0/T2/T3(星座)/T5(进度)/email(female)/错误横幅/Back 恢复，均为 390×844 |
| `normal-run-commit-stats.json` | 全程渲染计数聚合（total=3611）+ byName |
| `normal-run-resource-timing.json` | 正常模式浏览器侧网络瀑布（39 条 API/导航） |
| `latency-500ms-network.jsonl` | 注入延迟时代理侧请求日志（505–535ms） |
| `failure-retry-network.jsonl` | 失败/重试场景代理侧请求日志（含 cold bootstrap 全序列） |
| `recording-proxy.mjs` | 录制插桩代理源码（/tmp 运行；HTML 注入 hook + fetch 重写 + 模式切换 + 会话重置） |

录屏由录制器脚本化动作模式产出（select+delay 显式序列）；`rec-1` 首次后台录制尝试产物为空已废弃（见 §8）。

## 8. NOT_RUN 与限制

| 项 | 状态 | 原因 |
|---|---|---|
| 真实移动设备（iOS Safari / Android Chrome：地址栏、旋转、键盘、安全区、滚轮惯性） | **NOT_RUN** | 环境无真机/WebKit 工具；批次 1 验收涉及真机项时需 owner 提供设备或工具 |
| 320/375/430/768/1440 视口 | **NOT_RUN**（本批仅 390 基线） | 批次 0 范围为 390 基线表现；全视口矩阵属批次 1+ 验收 |
| 原生触摸拖拽/惯性滚动手势 | **NOT_RUN**（合成鼠标拖拽不触发原生滚动） | 插桩局限；已用滚轮事件滚动 + 点选替代，批次 4 需真机手势记录 |
| 完整 HAR（请求头/时序分解） | 部分 | 以浏览器 resource timing + 代理日志替代（无 CDP 网络域访问） |
| `rec-1` 后台录制 | 失败（空 WebM） | IAB 录制器在无脚本动作时不产帧；已改用脚本化动作录制（全部有效录屏由此产出） |
| q18 多选页静态截图 | 视频帧替代 | R5 首次脚本在 T5 Continue 选择器上失败；q18→T5 段由 `rec-5` 开头覆盖 |
| T1/T4 静态截图 | 视频帧替代 | T1/T4 视觉已在 SP-104 证据核验；本批录屏覆盖其切换 |

## 9. 对后续批次的输入

1. **批次 1（背景/安全区）**：基线确认三处 390px 限宽来源（soulmate `layout.tsx` main、QuizShell/TransitionShell 根、FlowShellFallback）与 email 自有背景；390 下几何以本批截图为对照基准。
2. **批次 2（提交反馈）**：单选点击 = 整组选项重渲染（QuizPageContent 全量，49 fibers）是当前行为；失败路径的"选中态保留 + 原地 Retry"已成立，改造时不得回退（截图 `failure-error-banner-q02.png` 为对照）。
3. **批次 3（阶段切换数据准备）**：warm 路径已无重复 bootstrap；剩余优化点为冷启动 ~3400 commits 挂载突发与延迟下 4 次串行 bootstrap 调用的体感。
4. **批次 4（滚轮隔离）**：~~`63b2902` 上滚轮滚动已不触发 `QuizPageContent` 逐行更新，且显示值=提交值~~ **更正（2026-09-30，SP-1105）**："已隔离"结论源于插桩标签伪影（见 §5.1）；基线期实现实为逐行 `onChange` 驱动父组件更新。批次 4 已交付本地 draft + 结算提交，隔离以 SP-1105 的修正归因实测为准；"显示值=提交值"结论保持有效（Taurus 服务端核验）。批次 4 的验收应以此为本底，重点转向真机手势/结算定时器行为，而非本机已满足的隔离性。
