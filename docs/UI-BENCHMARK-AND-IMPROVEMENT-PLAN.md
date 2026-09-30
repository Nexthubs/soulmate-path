# Soulmate Path 问卷 UI 对比分析与改进方案 (Benchmark & Improvement Plan)

> **文档状态：** PROPOSED  
> **对比标杆：** [Stella Soulmate Quiz 线上生产环境 (`https://www.stella.love/soulmate/quiz`)](https://www.stella.love/soulmate/quiz)  
> **分析对象：** Soulmate Path 当前前端实现 (`frontend/src/`)  
> **核心目标：** 解决背景多尺寸设备兼容性缺陷、消灭单选点击与滚轮交互顿挫感、消除页面切换加载瀑布流，达到媲美线上标杆的流畅原生体验。

---

## 一、现状与核心缺陷诊断

经过对线上参考项目（stella.love）的生产资源与当前项目代码库的深入比对，当前项目在**视觉多尺寸适配**与**交互流畅性**上存在以下系统性缺陷：

### 1. 核心缺陷归纳

1. **大屏与多尺寸背景断层：**
   * 外层布局强行限制 `max-w-[390px]` 并设置阴影与白底，在任何宽度大于 390px 的设备（如主流大屏手机 412px~430px、iPad、PC/Mac 桌面）上呈现为一个被硬生生截断的狭窄卡片，两侧露出突兀的米白色空白。
2. **移动端安全区与动态视口缺失：**
   * 源码中**零处使用** `env(safe-area-inset-bottom)`，且全盘依赖传统的 `min-h-screen`（`100vh`），在 iOS Safari 和 Android Chrome 中存在地址栏收缩时的跳跃问题，且底部操作按钮容易紧贴或被手势条遮挡。
3. **单选点击视觉感知断裂（最大卡顿感来源）：**
   * 用户点击单选选项后，代码立即将该卡片透明度降为 `opacity-50`（置灰），并**同步等待网络接口往返**（200ms~800ms 不等）加上额外的 150ms 延时。用户感知为“刚点完按钮就死掉/变灰半秒以上才切题”。
4. **滚轮选择器（WheelDatePicker）性能重负载：**
   * 原生 `onScroll` 事件无防抖、无节流，滑动过程中的每一帧像素位移都在触发顶层 `QuizPageContent` 的全量 React 重新渲染，导致滚轮在移动端滑动时严重掉帧、卡顿、跳跃。
5. **过渡页面（Loading/Transitions）加载瀑布与闪烁：**
   * 问卷与过渡页之间采用 Next.js 路由硬跳转，导致 `<Suspense>` 骨架屏闪烁；进入过渡页后 Continue 按钮默认被禁用，必须等待 `getFlowState` 网络接口返回后才点亮，点击后又必须等待接口才能切回，整体流程被切割得极其断续。

---

## 二、线上项目（stella.love）架构与实现剖析

通过对线上页面及其核心资源（`quiz.CMraUptE.css`、`loading.B2HeBixH.css`、`DUhMSSa4.js`、`DHIxBbFG.js`）的反编译分析，线上项目的设计规范如下：

### 1. 通栏背景与流式自适应架构
* **全屏背景铺底：**
  ```css
  .page-viewport {
    min-height: 100dvh;
    min-height: 100vh;
    min-height: -webkit-fill-available;
    width: 100%;
  }
  .sm-quiz, .sm-loading {
    background: linear-gradient(180deg, #fdf2f8, #fef3c7), #fff;
    width: 100vw;
    min-height: 100dvh;
    padding: 5.25rem 1.35rem calc(8.75rem + env(safe-area-inset-bottom));
  }
  ```
  渐变底色挂在 100vw 的最外层，多尺寸下始终无缝通栏。
* **居中约束内容槽：**
  ```css
  .sm-quiz__main {
    max-width: 26rem; /* 416px */
    margin: 0 auto;
    width: 100%;
  }
  ```
  只限制正文内容的宽度为 416px，大屏居中展现，小屏自然撑满。
* **底部悬浮 Dock：**
  ```css
  .sm-quiz__dock {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    background: linear-gradient(180deg, #fef3c800, #fef3c7 18%, #fef3c7);
    padding: 0.85rem 1.35rem calc(1.15rem + env(safe-area-inset-bottom));
  }
  ```
  遮罩通栏且自适应 Home Indicator，内部按钮按 26rem 居中。

### 2. 单选点击即时高亮与舒适微延时
* **即时反馈与零透明度惩罚：**
  ```javascript
  // 1. 点击时立即高亮卡片（边框加粗加深，勾选图标显示），保持 100% 鲜明饱和度
  selected.value = [optionId];
  isLocked = true; // 仅做逻辑防重，绝不改变 CSS 视觉透明度
  
  // 2. 保证 DOM 渲染后，提供舒适的 320ms 视觉驻留确认感
  await nextTick();
  await new Promise(resolve => setTimeout(resolve, 320));
  
  // 3. 无缝切入下一题
  advanceToNextStep();
  ```
  不因防重而置灰卡片，用户感知平滑、肯定。

### 3. 硬件加速与滚轮防抖
* **Touch 惯性滚动与 GPU 遮罩：**
  ```css
  .sm-picker__body {
    mask-image: linear-gradient(180deg, transparent, #000 18%, #000 82%, transparent);
    -webkit-mask-image: linear-gradient(180deg, transparent, #000 18%, #000 82%, transparent);
  }
  .sm-picker__col {
    scroll-snap-type: y mandatory;
    -webkit-overflow-scrolling: touch;
  }
  ```
* **80ms 滚动防抖（Debounce）与滚动状态锁：**
  滑动中途不触发大量组件重绘，停止滑动后计算最终吸附索引，保证 60fps 满帧滑动。

---

## 三、当前项目代码实现与缺陷对照

| 维度 | 线上项目（stella.love） | 当前项目实现 | 当前受影响文件与行号 |
| :--- | :--- | :--- | :--- |
| **容器背景** | 根节点全屏 `100vw` 铺通栏渐变，内部内容 `max-w: 26rem` | 外层强制限制 `max-w-[390px]` 居中盒子，外露米白底 | [`layout.tsx#L28`](file:///Users/zhaozhao/AI%20Coding/Soumate%20Path/frontend/src/app/soulmate/layout.tsx#L28), [`globals.css#L6`](file:///Users/zhaozhao/AI%20Coding/Soumate%20Path/frontend/src/app/globals.css#L6) |
| **安全区适配** | `env(safe-area-inset-bottom)` 计算 padding | **零使用**，底部固定 `pb-10` | [`QuizShell.tsx#L202`](file:///Users/zhaozhao/AI%20Coding/Soumate%20Path/frontend/src/soulmate/components/quiz/QuizShell.tsx#L202), [`TransitionShell.tsx#L127`](file:///Users/zhaozhao/AI%20Coding/Soumate%20Path/frontend/src/soulmate/components/transition/TransitionShell.tsx#L127) |
| **视口单位** | `100dvh` / `100vh` / `-webkit-fill-available` | 仅使用普通 `min-h-screen`（`100vh`） | [`layout.tsx#L28`](file:///Users/zhaozhao/AI%20Coding/Soumate%20Path/frontend/src/app/soulmate/layout.tsx#L28), [`QuizShell.tsx#L91`](file:///Users/zhaozhao/AI%20Coding/Soumate%20Path/frontend/src/soulmate/components/quiz/QuizShell.tsx#L91) |
| **排版字号** | CSS `clamp(1.6rem, 6.4vw, 2rem)` 流式排版 | 固定像素 `text-[20px] leading-[30px]` | [`QuizShell.tsx#L135-L142`](file:///Users/zhaozhao/AI%20Coding/Soumate%20Path/frontend/src/soulmate/components/quiz/QuizShell.tsx#L135-L142) |
| **单选反馈** | 保持 100% 鲜明高亮，320ms 舒适停留后平滑切题 | 点击立即置灰 `opacity-50`，且同步等待网络 RTT | [`OptionCard.tsx#L88`](file:///Users/zhaozhao/AI%20Coding/Soumate%20Path/frontend/src/soulmate/components/quiz/OptionCard.tsx#L88), [`quiz/page.tsx#L326-L380`](file:///Users/zhaozhao/AI%20Coding/Soumate%20Path/frontend/src/app/soulmate/quiz/page.tsx#L326-L380) |
| **滚轮性能** | `-webkit-overflow-scrolling: touch` + 80ms 防抖 | 原生每帧 `onScroll` 触发全量 React 重新渲染 | [`WheelDatePicker.tsx#L89-L94`](file:///Users/zhaozhao/AI%20Coding/Soumate%20Path/frontend/src/soulmate/components/quiz/WheelDatePicker.tsx#L89-L94) |
| **过渡页体验** | 客户端状态机流转，Continue 按钮即刻可用 | 路由硬跳转 + 骨架屏闪烁 + `getFlowState` 阻塞启用 | [`loading/page.tsx#L69-L224`](file:///Users/zhaozhao/AI%20Coding/Soumate%20Path/frontend/src/app/soulmate/loading/page.tsx#L69-L224) |

---

## 四、详尽改进实施方案

改进方案完全遵循项目已建立的契约（`DEV-SPEC v1.2`、`AGENTS.md`），不改变任何后端 API 接口签名、不改动数据库与计费契约，纯粹在前端表现层与交互编排层进行重构升级。

### 阶段一：背景与全视口通栏改造 (Viewport & Background Overhaul)

#### 1.1 改造顶层 Layout (`frontend/src/app/soulmate/layout.tsx`)
* **改动前：**
  `<main className="w-full max-w-[390px] min-h-screen mx-auto flex flex-col relative shadow-sm bg-white">`
* **改动后：**
  * 将渐变底色提升至最外层 `layout`，设置 `min-h-[100dvh] w-full bg-gradient-to-b from-[#fff0f3] via-[#fef4e9] to-[#fef3de]`。
  * 移除外层强制的 `max-w-[390px]` 和 `shadow-sm`，让渐变底色自然铺满全屏（无论是 375px、430px、768px 还是桌面大屏）。
  * 在布局内建立满屏视口容器，将内容宽度约束（`max-w-[420px] w-full mx-auto`）下放给各页面主槽位。

#### 1.2 引入安全区与现代视口支持 (`frontend/src/app/globals.css`)
* 在 `globals.css` 中增加统一的视口与安全区实用类：
  ```css
  @supports (min-height: 100dvh) {
    .viewport-fill {
      min-height: 100dvh;
    }
  }
  @supports not (min-height: 100dvh) {
    .viewport-fill {
      min-height: 100vh;
      min-height: -webkit-fill-available;
    }
  }

  .safe-pb-dock {
    padding-bottom: calc(1.25rem + env(safe-area-inset-bottom, 0px));
  }
  .safe-pt-header {
    padding-top: calc(1rem + env(safe-area-inset-top, 0px));
  }
  ```

#### 1.3 升级主壳层布局 (`QuizShell.tsx` & `TransitionShell.tsx`)
* 去除内层冗余的 `bg-gradient-to-b` 与固定 `max-w-[390px]` 限制。
* 内部正文内容容器设置为 `max-w-[420px] w-full px-5 mx-auto`。
* 底部操作区域应用 `safe-pb-dock`，确保在 iPhone X~16 等全面屏机型上，操作按钮与 Home Indicator 保持标准间隙，杜绝手势条误触与遮挡。

---

### 阶段二：单选点击反馈与交互润滑 (OptionCard & Transition Latency)

#### 2.1 修复 `OptionCard` 置灰降透明度问题 (`OptionCard.tsx`)
* **根因：**
  当前代码中：
  ```tsx
  if (disabled) {
    stateClasses += " opacity-50 cursor-not-allowed pointer-events-none";
  }
  ```
* **改进方案：**
  * 区分「选中且正在提交」与「普通不可用」：
  * 当卡片处于 `selected === true` 状态时，即使处于 `disabled`（防止重复点击），**严禁应用 `opacity-50`**！
  * 保持深色边框、高亮背景与勾选图标，仅禁用指针事件（`pointer-events-none`）。
  * 为卡片添加轻微的触摸按压缩放反馈：`active:scale-[0.99]`，提升物理质感。

#### 2.2 优化切题等待流转 (`frontend/src/app/soulmate/quiz/page.tsx`)
* **改动逻辑：**
  1. 用户点击单选选项后，立即更新本地 `singleValue`（界面毫秒级呈现选中状态）。
  2. 启动逻辑防重锁（阻止二次点击）。
  3. 执行 `submitAnswer` 接口，同时启动一个平滑延时（约 280ms）。
  4. 采用 `Promise.all([submitPromise, delayPromise])` 模式：
     * 如果网络速度快（<200ms），用户会感受到恰好约 280ms 舒适的视觉驻留确认，随后无缝滑向下一题。
     * 避免了当前方案中“等完网络请求之后再硬等 150ms”的双重延迟叠加。
     * 若发生网络异常，在原卡片上就地展示重试提示，不发生页面跳动。

---

### 阶段三：滚轮日期选择器性能调优 (WheelDatePicker Performance)

#### 3.1 引入滚动防抖与组件重渲染隔离 (`WheelDatePicker.tsx`)
* **根因：**
  每一帧滚动事件都直接回调父级 `onChange`，触发整个页面的全量 React 重新渲染。
* **改进方案：**
  1. **本地状态解耦：** 在 `WheelColumn` 内部维护滚动的瞬时索引（使用 `useRef` 或轻量级内部 state），在滑动过程中仅更新高亮样式，不向顶层抛出昂贵的全局状态更新。
  2. **防抖结算：** 利用 `requestAnimationFrame` 或 80ms `setTimeout` 防抖机制，当滚轮停止滑动（吸附完成）时，才触发一次顶层 `onSelect` / `onChange`。
  3. **开启硬件加速：** 为滚轮滚动列添加 `-webkit-overflow-scrolling: touch;` 与 `transform: translateZ(0)`，激活移动端 WebKit 硬件加速。
  4. **CSS Mask 替代覆盖层：** 采用 CSS `mask-image` 实现上下边缘的平滑羽化渐变，消除白色覆盖层在不同底色下的边缘分层瑕疵。

---

### 阶段四：过渡页面流畅度与渲染瀑布消除 (Transitions Smoothing)

#### 4.1 预置流转上下文，消除 Continue 按钮禁用等待 (`loading/page.tsx`)
* **根因：**
  每次进入 `/soulmate/loading`，必须等待网络请求 `getFlowState` 完成才将 `continueDisabled` 设为 `false`。
* **改进方案：**
  * 利用已有的大局共享上下文 [`SharedFlowContext`](file:///Users/zhaozhao/AI%20Coding/Soumate%20Path/frontend/src/soulmate/components/flow/SharedFlowContext.tsx)：
  * 从问卷进入过渡页时，前序步骤已经明确知道目标是 `transition_X`，此时将当前有效的上下文与 metadata 直接带入。
  * Continue 按钮在挂载时即刻处于可用状态（无需置灰等待接口握手）。
  * 仅在用户实际点击 Continue 时异步发送推进请求，彻底消除“进页面先看禁用灰色按钮”的不良体验。

#### 4.2 避免不必要的 Suspense 白屏闪烁
* 确保在问卷页面与过渡页面之间的跳转过程中，Next.js 的路由切换不卸载顶层布局，保持全屏渐变背景持续稳定挂载，杜绝闪白或骨架屏突变。

---

## 五、实施步骤与验证清单

### 1. 实施顺序与分支策略
1. **Task 1: Viewport & Layout 通栏重构**
   * 修改 `layout.tsx`、`globals.css`、`QuizShell.tsx`、`TransitionShell.tsx`。
   * 验证全机型（320px ~ 1920px）背景通栏与安全区边距。
2. **Task 2: OptionCard 视觉与切题时延优化**
   * 修改 `OptionCard.tsx`、`quiz/page.tsx`。
   * 消除置灰 50% 现象，实现 280ms 并行微延时切题。
3. **Task 3: WheelDatePicker 性能隔离改造**
   * 修改 `WheelDatePicker.tsx`。
   * 验证 iOS Safari 与 Android 上 60fps 跟手滚动。
4. **Task 4: Transition 加载流润滑**
   * 修改 `loading/page.tsx` 与 `SharedFlowContext.tsx`。
   * 消除 Continue 按钮的接口依赖等待。

### 2. 多设备验收矩阵 (Verification Matrix)

| 测试机型 / 视口 | 核心验证点 | 预期合格标准 |
| :--- | :--- | :--- |
| **iPhone SE (375 × 667)** | 小屏排版与字号自适应 | 标题无非预期断行，底部按钮不贴底，无横向溢出 |
| **iPhone 16 Pro Max (430 × 932)** | 大屏背景通栏与安全区 | 左右无断层空白，底栏避开手势条，背景通栏铺满 |
| **Android Pixel 7 (412 × 915)** | 动态地址栏缩放 | 滚动时页面高度无突变抖动，无闪烁 |
| **iPad Air (820 × 1180)** | 平板居中体验 | 背景全屏渐变通栏，内容居中在 416px 内，视觉舒适 |
| **Desktop Chrome (1440 × 900)** | 宽屏桌面体验 | 背景自然延伸，无突兀硬阴影卡片边框 |
| **弱网环境 (3G / 慢网模拟)** | 交互反馈与状态保护 | 点击单选项保持高亮确认，不灰显卡死，超时平稳报错 |
