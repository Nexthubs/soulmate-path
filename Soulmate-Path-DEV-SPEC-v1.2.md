# Soulmate Path Development Specification v1.2

> **文档状态**：Ready for implementation — context-optimized source-of-truth edition  
> **目标读者**：前端 / 后端 / QA / DevOps / 产品 / coding agents  
> **基准日期**：2026-09-23  
> **Figma**：Soulmate Path — `KJJj7uT7uQfmsbRt55nwMn`  
> **产品源文件**：`灵魂伴侣PRD.md`、`灵魂伴侣问题&选项.xlsx`  
> **执行配套**：`AGENTS.md`、`TASK-BREAKDOWN.md`、`PROJECT-STATE.md`、`DECISIONS.md`

### v1.2 变更摘要

- DEV-SPEC 只保留产品与技术契约，不再重复 Task 拆解、Agent 执行规则、Milestone Governance 与当前 TBD 状态表。
- 任务范围/依赖/验收/Milestone Gate 统一由 `TASK-BREAKDOWN.md` 管理。
- Agent 工作方式、handoff/review 证据协议统一由 `AGENTS.md` 管理。
- 当前决策状态统一由 `DECISIONS.md` 管理；`RESOLVED` decision 可显式覆盖旧 baseline。
- 当前进度与下一安全任务统一由 `PROJECT-STATE.md` 管理。
- 采用 selective context loading：任务通过 `Spec refs / Decision refs / Depends` 精确加载上下文。

> **重要：** 本文不再包含开发任务列表和 Agent Governance。不要把它们重新复制进本文；请分别维护 `TASK-BREAKDOWN.md` 与 `AGENTS.md`。

---
## 0. 文档约定与来源优先级

本规格把三类材料合并成一套可执行实现：

1. **产品需求**：`灵魂伴侣PRD.md`。  
2. **题目数据**：`灵魂伴侣问题&选项.xlsx`。  
3. **视觉/交互**：Figma `Soulmate Path`。  
4. **外部技术约束**：PayPal 官方 Subscriptions API、OpenAI 官方 Image API。

若三者存在冲突，按以下原则处理：

- 用户可见文案/视觉：优先 Figma，但 Excel 中的题目与选项文本是 Quiz 数据源。
- 业务规则：优先 PRD。
- 题号与答案含义：优先 Excel。
- 第三方接口字段与事件名：优先对应厂商当前官方 API 文档。
- 本规格中额外加入的工程设计会标记为 **[DEV DECISION]**。
- 尚无产品依据的内容会标记为 **[TBD]**，不得由开发自行发明业务文案或收费规则。

### 0.1 已发现且必须显式处理的源材料差异

**DOMAIN-01**：PRD 同时出现 `stell.love` 与 `stella.love`。实现中不得硬编码域名，统一使用 `APP_BASE_URL`，生产域名由部署配置确定。

**QUIZ-01**：Excel 中 `Q2 = Select your gender`，`Q3 = Who are you interested in?`。PRD 的 Email/Subscribe 视觉和 Sketch 人物性别均取“问题 3”，因此：
- `Q2 -> user_gender`
- `Q3 -> preferred_partner_gender`
- 绝不能把两者都命名为 `gender`。

**PROMPT-01**：PRD 指定 Sketch 输入为 Q3/Q5/Q6/Q7，并把 Q7 传入 Prompt 的 `features`。但 Q7 实际问的是 soulmate 的关键品质（Kindness/Loyalty/Intelligence...），不是外貌特征。V1 为保持需求一致，仍执行 `Q7 -> features`；后续如要提高画像可控性，应由产品重新定义 Q7 或 Prompt 字段，不得由开发私自改题义。

**COPY-01**：Excel Q11 的显示文案为 `Dealing with uncertainly`。本规格保留源文案；是否改为 `uncertainty` 由产品确认后再修改显示文本，内部 code 已使用 `dealing_with_uncertainty`。

**PAYPAL-01**：月订阅的“首月优惠价”和“之后正常月费”已确定，但具体金额未提供。本规格用 `INTRO_PRICE` / `REGULAR_PRICE` 占位，禁止在代码里写死临时价格。

**REPORT-01**：PRD/Figma 有 Soulmate Report 页面，但没有定义报告生成模型、Prompt、答案映射规则。V1 必须先实现 Report 数据结构、状态机和渲染器；AI 报告生成 Provider 做成可插拔接口，正式 Prompt/Model 未确认前不得自行生成生产文案。

---


### 0.2 Companion document ownership

本文只定义稳定业务/技术 contract。其他事实的唯一维护位置：

- Task / dependency / acceptance / milestone → `TASK-BREAKDOWN.md`
- Agent execution / evidence / review protocol → `AGENTS.md`
- Current decision status / overrides → `DECISIONS.md`
- Current implementation state → `PROJECT-STATE.md`

任务应通过 `TASK-BREAKDOWN.md` 中的 `Spec refs` 按需读取本文相关章节，不要求默认全文加载。


# 1. V1 产品范围

## 1.1 主流程

```text
/soulmate
  Landing
    ↓
  Transition-0
    ↓
  Q02 → Q03 → Q04 → Q05 → Q06
    ↓
  Transition-1
    ↓
  Q07
    ↓
  Transition-2
    ↓
  Q08 → Q09 → Q10
    ↓
  Transition-3
    ↓
  Q11
    ↓
  Transition-4
    ↓
  Q12 → Q13 → Q14 → Q15 → Q16 → Q17 → Q18
    ↓
  Transition-5
    ↓
  Popup-1 Spiritual
    ↓
  Popup-2 Psychic Artistry
    ↓
  Popup-3 Warning
    ↓
  Email Capture
    ↓
  PayPal Subscription
    ↓
  Payment Confirmation
    ↓
  Soulmate Result / Dashboard
    ├── Sketch: 12h unlock
    └── Report: 24h unlock
```

## 1.2 V1 必须包含

- Landing 与 Login 入口。
- 17 个问题步骤（Q02–Q18）。
- Single / Multi / Date 三种题型。
- Transition-0 ~ Transition-5。
- Transition-5 的三个弹窗。
- Quiz 服务端持久化与刷新恢复。
- Email Capture。
- 根据 Q3 切换 male/female 视觉。
- Email 页展示 Q3/Q5/Q6 摘要。
- PayPal 月度订阅。
- 首月优惠价、第二个月起正常月费。
- PayPal Webhook 验签、幂等、支付流水。
- 支付成功后 Sketch 12 小时、Report 24 小时倒计时。
- Sketch AI 生成、重试、对象存储、唯一生成约束。
- Report 页面与结构化数据渲染。
- Drawer 的 Soulmate Sketch 入口。
- Settings 的订阅状态/取消入口。
- 核心埋点、错误监控、E2E 测试。

## 1.3 V1 不应自行扩展

- 新增 Excel 中不存在的正式 Quiz 问题。
- 自行改变星座边界。
- 自行更换 Sketch Prompt 的 Q3/Q5/Q6/Q7 输入逻辑。
- 自行定义 Report 的占卜/心理结论。
- 自行决定首月优惠是否“每个邮箱终身一次”。
- 自行发布未经证实的用户评价、销量或评分数据。

---

# 2. Figma 页面映射

| 功能 | Figma Node | Route | 组件建议 |
|---|---:|---|---|
| 抽屉页 | `102:14` | Global | `AccountDrawer` |
| 首页 | `102:44` | `/soulmate` | `SoulmateLandingPage` |
| 单选题 | `102:121` | `/soulmate/quiz` | `SingleChoiceQuestion` |
| 多选题 | `102:201` | `/soulmate/quiz` | `MultiChoiceQuestion` |
| 过渡-0 | `102:245` | `/soulmate/loading?step=0` | `TransitionPage` |
| 过渡-1 | `102:304` | `/soulmate/loading?step=1` | `TransitionPage` |
| 过渡-2 | `102:320` | `/soulmate/loading?step=2` | `TransitionPage` |
| 过渡-3 | `102:345` | `/soulmate/loading?step=3` | `TransitionPage` |
| 过渡-4 | `102:372` | `/soulmate/loading?step=4` | `TransitionPage` |
| 过渡-5 | `102:386` | `/soulmate/loading?step=5` | `TransitionPage` |
| 过渡-5弹窗1 | `102:425` | 同页 modal | `InterstitialQuestionModal` |
| 过渡-5弹窗2 | `102:466` | 同页 modal | `InterstitialQuestionModal` |
| 过渡-5弹窗3 | `102:445` | 同页 modal | `WarningModal` |
| 填邮箱，prefer女 | `102:486` | `/soulmate/email` | `EmailCapturePage` variant |
| 填邮箱，prefer男 | `102:557` | `/soulmate/email` | `EmailCapturePage` variant |
| 灵魂伴侣订阅页 | `102:655`, `102:928` | `/soulmate/subscribe` | `SoulmateSubscribePage` variant |
| 订阅成功 | `102:1201` | `/soulmate/result` | `SoulmateResultPage` |
| 报告产出状态 | `102:1332` | result 内 | `ReportReadyCard` |
| 灵魂伴侣画像 | `102:461` | `/soulmate/sketch` | `SoulmateSketchPage` |
| 灵魂伴侣报告 | `102:1358` | `/soulmate/report` | `SoulmateReportPage` |
| 设置页 | `102:1423`, `102:1460` | 现有设置路由 | `SubscriptionSettings` |

### 2.1 视觉实现约束

- 设计基线：390px mobile。
- Quiz 主字体：Poppins；品牌标题可用 Instrument Serif。
- Landing/Quiz 背景核心为粉色→浅黄色渐变。
- Single/Multi 的 option card 必须复用同一基础组件，仅改变 selection behavior。
- 结果页使用独立的 premium/glow 卡片视觉。
- 不允许把每一道题复制成单独页面组件。
- Figma MCP 返回的临时 asset URL 不得进入生产代码；图标/图片应从 Figma 导出后进入项目静态资源或 CDN。

---

# 3. 前端路由与 Guard

```text
GET /soulmate
GET /soulmate/quiz
GET /soulmate/loading?step=0..5
GET /soulmate/email
GET /soulmate/subscribe
GET /soulmate/payment-processing
GET /soulmate/result
GET /soulmate/sketch
GET /soulmate/report
```

### Route Guard

| Route | 最低条件 | 不满足时 |
|---|---|---|
| `/soulmate/quiz` | 有 active session | 新建 session |
| `/soulmate/email` | Quiz 已完成 | 回到当前 quiz step |
| `/soulmate/subscribe` | Email 已提交 | `/soulmate/email` |
| `/soulmate/result` | 首笔支付已确认 | `/soulmate/subscribe` |
| `/soulmate/sketch` | 首笔支付已确认且 12h 已解锁 | `/soulmate/result` |
| `/soulmate/report` | 首笔支付已确认且 24h 已解锁 | `/soulmate/result` |

**[DEV DECISION]** Guard 必须由服务端状态最终裁决；前端状态仅用于减少无效跳转，不能作为权限控制。

---

# 4. Quiz Engine

## 4.1 题目清单

| Code | Type | Question | Result Key | Options | 特殊用途 |
|---|---|---|---|---|---|
| q02 | single | Select your gender | `user_gender` | `male` — Male<br>`female` — Female | 用户自身性别；仅画像资料/分析使用，不作为画中人物性别 |
| q03 | single | Who are you interested in? | `preferred_partner_gender` | `male` — 👨‍Male<br>`female` — 👩‍Female | 画中 soulmate 性别；Email/订阅页视觉 variant；Sketch gender |
| q04 | single | What best describes your love life right now? | `love_life_status` | `single` — 🌱Single<br>`in_relationship` — 💞In a relationship<br>`engaged_or_married` — 💍Engaged or married<br>`recently_out` — 💔Recently out of something<br>`complicated` — 🌀It's complicated | 关系现状；报告输入 |
| q05 | single | Ideal age range for your soulmate? | `preferred_partner_age_range` | `age_20_30` — 👨‍20-30<br>`age_30_40` — 👨‍30-40<br>`age_40_50` — 👱‍♂️40-50<br>`age_50_plus` — 👨‍🦳50+ | Email 摘要；Sketch age_range |
| q06 | single | Do you have a preferred ethnic background for your sketch? | `preferred_partner_ethnicity` | `caucasian_white` — 🧑Caucasian/White<br>`hispanic_latino` — 👱Hispanic/Latino<br>`african_african_american` — 🧑🏾African/African-American<br>`asian` — 🧑🏻Asian<br>`no_preference` — 🙄No preference | Email 摘要；Sketch ethnicity |
| q07 | single | What’s the key quality your soulmate should have? | `key_soulmate_quality` | `kindness` — 😇Kindness<br>`loyalty` — 🥹Loyalty<br>`intelligence` — 🧐Intelligence<br>`creativity` — 🤩Creativity<br>`passion` — 🥰Passion<br>`empathy` — 😊Empathy | Transition-2；Sketch features（按现 PRD 直接映射，见风险项 PROMPT-01） |
| q08 | date | What's your date of birth?Your birth date reveals your core personality traits, needs and desires. | `birth_date` | 日期输入 | 计算 zodiac_sign；Transition-3 |
| q09 | single | Which of the four elements match your personality? | `element` | `fire` — 🔥Fire<br>`water` — 🌊Water<br>`earth` — ⛰Earth<br>`wind` — 💨Wind | 报告输入 |
| q10 | single | Do you make decisions with your head or your heart? | `decision_style` | `heart` — ❤Heart<br>`head` — 🧠Head<br>`both` — ⚖️Both | Transition-3 动态文案；报告输入 |
| q11 | single | What’s your biggest personal challenge? | `personal_challenge` | `building_trust` — 🤲🏻Building trust<br>`finding_right_person` — 👩🏼‍❤️‍👨🏼Finding the right person<br>`keeping_spark_alive` — 🔥Keeping the spark alive<br>`understanding_my_needs` — 🧘🏻Understanding my needs<br>`letting_go_past` — 🌈Letting go of the past<br>`dealing_with_uncertainty` — ⛅Dealing with uncertainly | 报告输入；Transition-4 前置 |
| q12 | single | What is your biggest red flag? | `red_flag` | `lack_of_trust` — 🙁Lack of trust<br>`poor_communication` — 😶Poor communication<br>`jealousy` — 🫣Jealousy<br>`disrespect` — 😢Disrespect<br>`inconsistency` — 🤯Inconsistency<br>`self_centeredness` — 😎Self-centeredness | 报告输入 |
| q13 | single | Do you prefer a similar partner or one who contrasts with you? | `similarity_preference` | `similar_to_me` — 😌Similar to me<br>`brings_contrast` — 🤩Brings contrast | 报告输入 |
| q14 | single | What’s your ideal relationship dynamic? | `relationship_dynamic` | `partnership` — 💞Partnership<br>`friendship` — 💓Friendship<br>`adventure` — ⛵Adventure<br>`deep_connection` — 💖Deep connection<br>`balanced_growth` — 🎯Balanced growth | 报告输入 |
| q15 | single | What’s your primary love language? | `love_language` | `words_of_affirmation` — 💖Words of affirmation<br>`acts_of_service` — 💕Acts of service<br>`physical_touch` — 💓Physical touch<br>`receiving_gifts` — 🎁Receiving gifts<br>`quality_time` — ⏳Quality time | 报告输入 |
| q16 | single | What’s your ideal connection with a partner? | `connection_style` | `deep_and_intimate` — 💋Deep and intimate<br>`fun_and_adventurous` — 🥳Fun and adventurous<br>`balanced_and_supportive` — 🪢Balanced and supportive<br>`passionate_and_inspiring` — 🌅Passionate and inspiring<br>`calm_and_steady` — 🧘🏻Calm and steady<br>`growth_and_learning` — 🧠Full of growth and learning<br>`other` — 🙄Other | 报告输入 |
| q17 | single | What’s your biggest relationship fear? | `relationship_fear` | `losing_trust` — 💔Losing trust<br>`growing_apart` — 🏃🏻‍♀️Growing apart<br>`not_being_understood` — 🤷Not being understood<br>`lack_of_commitment` — 🙅Lack of commitment<br>`being_vulnerable` — 🥹Being vulnerable<br>`getting_hurt_again` — 😢Getting hurt again<br>`other` — 🙄Other | 报告输入 |
| q18 | multi | What life goals do you hope to achieve with your soulmate? | `life_goals` | `building_a_family` — 👩‍❤️‍👨Building a family<br>`traveling_the_world` — ✈️Traveling the world<br>`creating_a_business` — 💼Creating a business<br>`personal_growth` — 🚀Personal growth<br>`financial_stability` — 💵Financial stability<br>`making_positive_impact` — 🎯Making a positive impact<br>`other` — 🙄Other | 多选；报告输入；完成后进入 Transition-5 |

> Q8 在 Excel 的题目与说明写在同一单元格。实现中拆为 `title` + `subtitle`，文案不改变。

## 4.2 Single 行为

```text
tap option
  ↓
local selected state
  ↓
lock interaction
  ↓
PUT answer
  ↓
success
  ↓
150–250ms selection feedback
  ↓
next step
```

要求：
- 点击选项立即进入下一步。
- 请求提交期间禁止第二次选择。
- 服务端采用 upsert；同一个 `session_id + question_code` 只能有一份有效答案。
- 网络失败时停留当前题并允许 retry。
- Back 返回后必须恢复已选答案。

## 4.3 Multi 行为

Q18：
- `min_select = 1`
- `max_select = null`
- 0 项时 Next disabled。
- >=1 项时 Next enabled。
- 点击 Next 才提交完整数组。
- option code 去重，服务端拒绝不在配置中的 value。

## 4.4 Date 行为

Q8：
- 使用真实日期值 `YYYY-MM-DD`。
- 服务端验证合法日期。
- 未定义最小/最大年龄；**[TBD AGE-01]** 上线前产品/法务决定是否限制未成年人。
- 星座在服务端计算，客户端不得成为唯一来源。

## 4.5 Quiz 配置版本

V1 固定：

```text
soulmate-quiz-v1
```

Session 创建时写入 `quiz_version`。旧 session 必须继续使用创建时的版本，避免改题后解释旧答案错误。

Excel 仅作为产品源文件，不建议生产运行时解析。推荐：

```text
灵魂伴侣问题&选项.xlsx
    ↓ import/validate script
soulmate-quiz-v1.json
    ↓ review / commit
DB quiz_versions.config_json
```

## 4.6 Canonical Quiz JSON

```json
{
  "version": "soulmate-quiz-v1",
  "questions": [
    {
      "code": "q02",
      "order": 2,
      "type": "single",
      "title": "Select your gender",
      "required": true,
      "result_key": "user_gender",
      "options": [
        {
          "code": "male",
          "label": "Male"
        },
        {
          "code": "female",
          "label": "Female"
        }
      ]
    },
    {
      "code": "q03",
      "order": 3,
      "type": "single",
      "title": "Who are you interested in?",
      "required": true,
      "result_key": "preferred_partner_gender",
      "options": [
        {
          "code": "male",
          "label": "👨‍Male"
        },
        {
          "code": "female",
          "label": "👩‍Female"
        }
      ]
    },
    {
      "code": "q04",
      "order": 4,
      "type": "single",
      "title": "What best describes your love life right now?",
      "required": true,
      "result_key": "love_life_status",
      "options": [
        {
          "code": "single",
          "label": "🌱Single"
        },
        {
          "code": "in_relationship",
          "label": "💞In a relationship"
        },
        {
          "code": "engaged_or_married",
          "label": "💍Engaged or married"
        },
        {
          "code": "recently_out",
          "label": "💔Recently out of something"
        },
        {
          "code": "complicated",
          "label": "🌀It's complicated"
        }
      ]
    },
    {
      "code": "q05",
      "order": 5,
      "type": "single",
      "title": "Ideal age range for your soulmate?",
      "required": true,
      "result_key": "preferred_partner_age_range",
      "options": [
        {
          "code": "age_20_30",
          "label": "👨‍20-30"
        },
        {
          "code": "age_30_40",
          "label": "👨‍30-40"
        },
        {
          "code": "age_40_50",
          "label": "👱‍♂️40-50"
        },
        {
          "code": "age_50_plus",
          "label": "👨‍🦳50+"
        }
      ]
    },
    {
      "code": "q06",
      "order": 6,
      "type": "single",
      "title": "Do you have a preferred ethnic background for your sketch?",
      "required": true,
      "result_key": "preferred_partner_ethnicity",
      "options": [
        {
          "code": "caucasian_white",
          "label": "🧑Caucasian/White"
        },
        {
          "code": "hispanic_latino",
          "label": "👱Hispanic/Latino"
        },
        {
          "code": "african_african_american",
          "label": "🧑🏾African/African-American"
        },
        {
          "code": "asian",
          "label": "🧑🏻Asian"
        },
        {
          "code": "no_preference",
          "label": "🙄No preference"
        }
      ]
    },
    {
      "code": "q07",
      "order": 7,
      "type": "single",
      "title": "What’s the key quality your soulmate should have?",
      "required": true,
      "result_key": "key_soulmate_quality",
      "options": [
        {
          "code": "kindness",
          "label": "😇Kindness"
        },
        {
          "code": "loyalty",
          "label": "🥹Loyalty"
        },
        {
          "code": "intelligence",
          "label": "🧐Intelligence"
        },
        {
          "code": "creativity",
          "label": "🤩Creativity"
        },
        {
          "code": "passion",
          "label": "🥰Passion"
        },
        {
          "code": "empathy",
          "label": "😊Empathy"
        }
      ]
    },
    {
      "code": "q08",
      "order": 8,
      "type": "date",
      "title": "What's your date of birth?",
      "required": true,
      "result_key": "birth_date",
      "subtitle": "Your birth date reveals your core personality traits, needs and desires."
    },
    {
      "code": "q09",
      "order": 9,
      "type": "single",
      "title": "Which of the four elements match your personality?",
      "required": true,
      "result_key": "element",
      "options": [
        {
          "code": "fire",
          "label": "🔥Fire"
        },
        {
          "code": "water",
          "label": "🌊Water"
        },
        {
          "code": "earth",
          "label": "⛰Earth"
        },
        {
          "code": "wind",
          "label": "💨Wind"
        }
      ]
    },
    {
      "code": "q10",
      "order": 10,
      "type": "single",
      "title": "Do you make decisions with your head or your heart?",
      "required": true,
      "result_key": "decision_style",
      "options": [
        {
          "code": "heart",
          "label": "❤Heart"
        },
        {
          "code": "head",
          "label": "🧠Head"
        },
        {
          "code": "both",
          "label": "⚖️Both"
        }
      ]
    },
    {
      "code": "q11",
      "order": 11,
      "type": "single",
      "title": "What’s your biggest personal challenge?",
      "required": true,
      "result_key": "personal_challenge",
      "options": [
        {
          "code": "building_trust",
          "label": "🤲🏻Building trust"
        },
        {
          "code": "finding_right_person",
          "label": "👩🏼‍❤️‍👨🏼Finding the right person"
        },
        {
          "code": "keeping_spark_alive",
          "label": "🔥Keeping the spark alive"
        },
        {
          "code": "understanding_my_needs",
          "label": "🧘🏻Understanding my needs"
        },
        {
          "code": "letting_go_past",
          "label": "🌈Letting go of the past"
        },
        {
          "code": "dealing_with_uncertainty",
          "label": "⛅Dealing with uncertainly"
        }
      ]
    },
    {
      "code": "q12",
      "order": 12,
      "type": "single",
      "title": "What is your biggest red flag?",
      "required": true,
      "result_key": "red_flag",
      "options": [
        {
          "code": "lack_of_trust",
          "label": "🙁Lack of trust"
        },
        {
          "code": "poor_communication",
          "label": "😶Poor communication"
        },
        {
          "code": "jealousy",
          "label": "🫣Jealousy"
        },
        {
          "code": "disrespect",
          "label": "😢Disrespect"
        },
        {
          "code": "inconsistency",
          "label": "🤯Inconsistency"
        },
        {
          "code": "self_centeredness",
          "label": "😎Self-centeredness"
        }
      ]
    },
    {
      "code": "q13",
      "order": 13,
      "type": "single",
      "title": "Do you prefer a similar partner or one who contrasts with you?",
      "required": true,
      "result_key": "similarity_preference",
      "options": [
        {
          "code": "similar_to_me",
          "label": "😌Similar to me"
        },
        {
          "code": "brings_contrast",
          "label": "🤩Brings contrast"
        }
      ]
    },
    {
      "code": "q14",
      "order": 14,
      "type": "single",
      "title": "What’s your ideal relationship dynamic?",
      "required": true,
      "result_key": "relationship_dynamic",
      "options": [
        {
          "code": "partnership",
          "label": "💞Partnership"
        },
        {
          "code": "friendship",
          "label": "💓Friendship"
        },
        {
          "code": "adventure",
          "label": "⛵Adventure"
        },
        {
          "code": "deep_connection",
          "label": "💖Deep connection"
        },
        {
          "code": "balanced_growth",
          "label": "🎯Balanced growth"
        }
      ]
    },
    {
      "code": "q15",
      "order": 15,
      "type": "single",
      "title": "What’s your primary love language?",
      "required": true,
      "result_key": "love_language",
      "options": [
        {
          "code": "words_of_affirmation",
          "label": "💖Words of affirmation"
        },
        {
          "code": "acts_of_service",
          "label": "💕Acts of service"
        },
        {
          "code": "physical_touch",
          "label": "💓Physical touch"
        },
        {
          "code": "receiving_gifts",
          "label": "🎁Receiving gifts"
        },
        {
          "code": "quality_time",
          "label": "⏳Quality time"
        }
      ]
    },
    {
      "code": "q16",
      "order": 16,
      "type": "single",
      "title": "What’s your ideal connection with a partner?",
      "required": true,
      "result_key": "connection_style",
      "options": [
        {
          "code": "deep_and_intimate",
          "label": "💋Deep and intimate"
        },
        {
          "code": "fun_and_adventurous",
          "label": "🥳Fun and adventurous"
        },
        {
          "code": "balanced_and_supportive",
          "label": "🪢Balanced and supportive"
        },
        {
          "code": "passionate_and_inspiring",
          "label": "🌅Passionate and inspiring"
        },
        {
          "code": "calm_and_steady",
          "label": "🧘🏻Calm and steady"
        },
        {
          "code": "growth_and_learning",
          "label": "🧠Full of growth and learning"
        },
        {
          "code": "other",
          "label": "🙄Other"
        }
      ]
    },
    {
      "code": "q17",
      "order": 17,
      "type": "single",
      "title": "What’s your biggest relationship fear?",
      "required": true,
      "result_key": "relationship_fear",
      "options": [
        {
          "code": "losing_trust",
          "label": "💔Losing trust"
        },
        {
          "code": "growing_apart",
          "label": "🏃🏻‍♀️Growing apart"
        },
        {
          "code": "not_being_understood",
          "label": "🤷Not being understood"
        },
        {
          "code": "lack_of_commitment",
          "label": "🙅Lack of commitment"
        },
        {
          "code": "being_vulnerable",
          "label": "🥹Being vulnerable"
        },
        {
          "code": "getting_hurt_again",
          "label": "😢Getting hurt again"
        },
        {
          "code": "other",
          "label": "🙄Other"
        }
      ]
    },
    {
      "code": "q18",
      "order": 18,
      "type": "multi",
      "title": "What life goals do you hope to achieve with your soulmate?",
      "required": true,
      "result_key": "life_goals",
      "min_select": 1,
      "max_select": null,
      "options": [
        {
          "code": "building_a_family",
          "label": "👩‍❤️‍👨Building a family"
        },
        {
          "code": "traveling_the_world",
          "label": "✈️Traveling the world"
        },
        {
          "code": "creating_a_business",
          "label": "💼Creating a business"
        },
        {
          "code": "personal_growth",
          "label": "🚀Personal growth"
        },
        {
          "code": "financial_stability",
          "label": "💵Financial stability"
        },
        {
          "code": "making_positive_impact",
          "label": "🎯Making a positive impact"
        },
        {
          "code": "other",
          "label": "🙄Other"
        }
      ]
    }
  ]
}
```

---

# 5. Transition / Interstitial 规则

## 5.1 Step 顺序

```text
Transition-0 → Q02..Q06
Transition-1 → Q07
Transition-2 → Q08..Q10
Transition-3 → Q11
Transition-4 → Q12..Q18
Transition-5 → 3 popups → Email
```

## 5.2 Transition-0

- Figma `102:245`
- CTA 点击继续。
- 不产生业务答案。
- 埋点 `soulmate_transition_continue`，属性 `step=0`。

## 5.3 Transition-1

Figma `102:304` 示例核心文案包含：

```text
Your artist has started
Sketching now
```

V1 视为表现性文案，不表示后台已经调用 AI。

## 5.4 Transition-2

Figma `102:320` 示例使用 Q7=Intelligence：

```text
Awesome!
Those who seek Intelligence in their soulmate ...
```

**[TBD COPY-02]** 当前只确认了 `Intelligence` 示例，Kindness/Loyalty/Creativity/Passion/Empathy 的完整动态文案未在 PRD/Excel 中定义。工程层支持 mapping，但未提供的文案不得自行生成后直接上线。

配置结构：

```json
{
  "transition": "transition_2",
  "source_question": "q07",
  "copy_by_option": {
    "intelligence": "...Figma copy..."
  }
}
```

## 5.5 Transition-3：Zodiac + Q10

服务端根据 Q8 DOB 计算 zodiac：

| Sign | Range |
|---|---|
| Aries | 03-21 ~ 04-19 |
| Taurus | 04-20 ~ 05-20 |
| Gemini | 05-21 ~ 06-21 |
| Cancer | 06-22 ~ 07-22 |
| Leo | 07-23 ~ 08-22 |
| Virgo | 08-23 ~ 09-22 |
| Libra | 09-23 ~ 10-23 |
| Scorpio | 10-24 ~ 11-21 |
| Sagittarius | 11-22 ~ 12-20 |
| Capricorn | 12-21 ~ 01-20 |
| Aquarius | 01-21 ~ 02-19 |
| Pisces | 02-20 ~ 03-20 |

Q10 动态文案：

```text
heart → people make decisions using their heart.
head  → people make decisions using their head.
both  → people make decisions using their heart and head.
```

渲染数据：

```json
{
  "zodiac_label": "Virgo Sun",
  "decision_copy": "people make decisions using their heart and head."
}
```

边界日期必须有单元测试。

## 5.6 Transition-4

- Figma Node `102:372`。
- 业务规则未在 PRD/Excel 单独定义。
- **[TBD COPY-03]** 按 Figma 还原当前静态内容；如有动态变量，需产品补充映射，不由开发猜测。

## 5.7 Transition-5 + 三弹窗

Figma `102:386` 的进度视觉包括：

```text
Heart’s Intentions      100%
Portrait of the Soulmate 85%
Connection Insights      0%
```

这些在支付前出现，因此应视为营销/体验进度，不得绑定真实 AI Job progress。

弹窗顺序：

1. `Do you consider yourself a spiritual person?` → No / Yes
2. `Are you familiar with the concept of Psychic Artistry?` → No / Yes
3. Warning modal：`We have noticed something shocking ...` → Figma No / Yes

建议存储：

```text
spiritual_person: boolean
familiar_psychic_artistry: boolean
warning_response: yes|no
```

**[DEV DECISION]** 当前没有条件分支规则，No/Yes 均继续到下一步，仅用于画像/报告扩展或埋点。若产品希望分支，需要另补规则。

---

# 6. Session 与恢复机制

## 6.1 原则

用户不需要先登录才能开始 Quiz。

首次进入：

```text
POST /api/soulmate/sessions
→ set secure HttpOnly cookie: soulmate_sid
```

服务端为 source of truth；Local Storage 只可用于 UI 加速。

## 6.2 Session 状态

```text
CREATED
QUIZ_IN_PROGRESS
QUIZ_COMPLETED
EMAIL_CAPTURED
CHECKOUT_PENDING
SUBSCRIBED
ABANDONED
```

推荐字段：

```text
id
public_id
user_id nullable
email nullable
email_normalized nullable
quiz_version
status
current_step
utm_json
created_at
updated_at
quiz_completed_at
email_captured_at
subscription_success_at
```

`current_step` 使用稳定 step code，例如：

```text
transition_0
q02
...
q18
transition_5
email
subscribe
result
```

---

# 7. Normalized Soulmate Profile

Quiz 完成后生成一次规范化 Profile，并在答案变化时重算。

```ts
interface SoulmateProfileV1 {
  userGender: "male" | "female";
  preferredPartnerGender: "male" | "female";
  loveLifeStatus: string;
  preferredPartnerAgeRange: string;
  preferredPartnerEthnicity: string;
  keySoulmateQuality: string;

  birthDate: string;
  zodiacSign: string;
  element: "fire" | "water" | "earth" | "wind";
  decisionStyle: "heart" | "head" | "both";

  personalChallenge: string;
  redFlag: string;
  similarityPreference: string;
  relationshipDynamic: string;
  loveLanguage: string;
  connectionStyle: string;
  relationshipFear: string;
  lifeGoals: string[];

  spiritualPerson?: boolean;
  familiarPsychicArtistry?: boolean;
  warningResponse?: "yes" | "no";
}
```

用途：

```text
Raw Answers
   ↓
ProfileV1
   ├── Email summary
   ├── Subscribe variant
   ├── Transition copy
   ├── Sketch Prompt
   └── Report Generator
```

---

# 8. Email Capture

## 8.1 页面规则

- Q3=`male` → 使用 prefer 男视觉。
- Q3=`female` → 使用 prefer 女视觉。
- 下方三个信息严格取：
  - Q3 partner gender
  - Q5 age range
  - Q6 ethnicity

## 8.2 API

```http
POST /api/soulmate/sessions/:sessionId/email
Content-Type: application/json

{
  "email": "user@example.com"
}
```

Response：

```json
{
  "ok": true,
  "next": "/soulmate/subscribe"
}
```

## 8.3 Identity 规则

- Email Capture 的邮箱是产品联系/归属字段，不自动等同于已验证登录身份。
- PayPal payer email 可能与此邮箱不同，必须分别保存。
- 若用户已登录，session 可绑定 `user_id`。
- 若匿名，不得因为输入某个邮箱就授予该邮箱对应账户的访问权限。

---

# 9. PayPal Subscription

## 9.1 V1 计费模型

```text
Cycle 1: MONTH x 1, discounted price, exactly 1 cycle
Cycle 2+: MONTH x 1, regular price, infinite
```

PayPal Subscriptions API 把“有价格的优惠首月”也建模成 `TRIAL` billing cycle；用户 UI 不应写成“free trial”，而应明确展示：

```text
Today: ${INTRO_PRICE}
Then ${REGULAR_PRICE} / month
Automatically renews until canceled.
```

### 9.1.1 PayPal Plan 示例

```json
{
  "name": "Soulmate Monthly Intro",
  "product_id": "{PAYPAL_PRODUCT_ID}",
  "billing_cycles": [
    {
      "frequency": {
        "interval_unit": "MONTH",
        "interval_count": 1
      },
      "tenure_type": "TRIAL",
      "sequence": 1,
      "total_cycles": 1,
      "pricing_scheme": {
        "fixed_price": {
          "value": "{INTRO_PRICE}",
          "currency_code": "{CURRENCY}"
        }
      }
    },
    {
      "frequency": {
        "interval_unit": "MONTH",
        "interval_count": 1
      },
      "tenure_type": "REGULAR",
      "sequence": 2,
      "total_cycles": 0,
      "pricing_scheme": {
        "fixed_price": {
          "value": "{REGULAR_PRICE}",
          "currency_code": "{CURRENCY}"
        }
      }
    }
  ],
  "payment_preferences": {
    "auto_bill_outstanding": true,
    "payment_failure_threshold": 1
  }
}
```

## 9.2 Plan 创建方式

Plan 作为基础设施一次性创建，不在用户每次支付时创建。

```text
PayPal Product
   └── Soulmate Monthly Intro Plan
```

**[TBD PAY-02]** 如果将来确定“首月优惠每个用户/邮箱只能享受一次”，再同时创建：

```text
Soulmate Monthly Standard Plan
```

然后后端按 eligibility 选择 Plan。V1 当前需求只明确“第一次支付有首月优惠”，未定义重新订阅时是否还能再次享受，因此不要自行限制。

## 9.3 用户订阅流程

```text
Subscribe Page
  ↓
Frontend requests checkout config
  ↓
PayPal JS SDK / Create Subscription
  ↓
Buyer approves
  ↓
Frontend receives subscriptionID
  ↓
POST /api/soulmate/paypal/confirm
  ↓
Backend fetches PayPal subscription status
  ↓
Payment Processing screen
  ↓
Webhook PAYMENT.SALE.COMPLETED
  ↓
set subscription_success_at / first_payment_at
  ↓
/soulmate/result
```

前端 `onApprove` 不是最终支付成功依据。

## 9.4 订阅成功的业务定义

PRD 规定倒计时“从用户订阅成功后开始”。

V1 将内部 `subscription_success_at` 定义为：

```text
该 soulmate subscription 第一次收到且验签通过的
PAYMENT.SALE.COMPLETED.created_time
```

而不是：
- button click time
- approval time
- `BILLING.SUBSCRIPTION.CREATED`
- 客户端时间

然后：

```text
sketch_unlock_at = subscription_success_at + 12 hours
report_unlock_at = subscription_success_at + 24 hours
```

## 9.5 必须监听的 Webhook

```text
BILLING.SUBSCRIPTION.CREATED
BILLING.SUBSCRIPTION.ACTIVATED
BILLING.SUBSCRIPTION.UPDATED
BILLING.SUBSCRIPTION.PAYMENT.FAILED
BILLING.SUBSCRIPTION.SUSPENDED
BILLING.SUBSCRIPTION.CANCELLED
BILLING.SUBSCRIPTION.EXPIRED

PAYMENT.SALE.COMPLETED
PAYMENT.SALE.REFUNDED
PAYMENT.SALE.REVERSED
```

## 9.6 Webhook 安全

Endpoint：

```http
POST /api/webhooks/paypal
```

要求：

1. 读取 raw request body。
2. 验证 PayPal webhook signature。
3. 验签失败 → 4xx，不处理业务。
4. `event.id` 唯一入库。
5. 已处理 event → 返回 2xx，不重复执行业务。
6. 所有状态更新放在事务中。
7. 记录 `debug_id` / provider resource id 便于排障。

PayPal 会对非 2xx webhook 重试，因此幂等是硬要求。

## 9.7 支付失败

```text
PAYMENT_FAILED
  ↓
subscription.provider_status = ACTIVE/SUSPENDED based on PayPal
  ↓
update failed_payments_count
  ↓
UI shows billing problem
```

初始优惠首月付款未成功：
- 不设置 `subscription_success_at`
- 不启动 12h/24h
- 不授予 Soulmate result entitlement

后续续费失败：
- 已经生成的 Sketch/Report 不删除。
- 未来订阅权益如何降级由现有会员体系处理。

## 9.8 取消订阅

使用 PayPal Subscriptions v1：

```http
POST /v1/billing/subscriptions/<built-in function id>/cancel
```

在调用 PayPal cancel 前，先保存最近一次 PayPal `billing_info.next_billing_time` 为本地 `paid_through_at`。

**[DEV DECISION]** 即使 Provider 状态立即变为 `CANCELLED`，本产品已经支付周期内的本地 entitlement 可持续到 `paid_through_at`；已生成的 Sketch/Report 永久保留。这样把“停止未来续费”和“删除已购买内容”解耦。

---

# 10. Result / Countdown 状态机

不要用一个字段同时表示“是否解锁”和“是否生成”。

## 10.1 Availability

```text
LOCKED    now < unlock_at
UNLOCKED  now >= unlock_at
```

## 10.2 Generation

```text
NOT_STARTED
QUEUED
PROCESSING
COMPLETED
FAILED
```

## 10.3 前端组合态

| Availability | Generation | UI |
|---|---|---|
| LOCKED | any | Countdown |
| UNLOCKED | NOT_STARTED | Ready / Check Now |
| UNLOCKED | QUEUED/PROCESSING | Loading |
| UNLOCKED | COMPLETED | Open |
| UNLOCKED | FAILED | Retry / Support |

## 10.4 Result API

```http
GET /api/soulmate/result
```

Response：

```json
{
  "server_time": "2026-09-22T13:00:00Z",
  "subscription": {
    "provider": "paypal",
    "provider_status": "ACTIVE",
    "first_payment_at": "2026-09-22T13:00:00Z",
    "next_billing_at": "2026-10-22T13:00:00Z"
  },
  "sketch": {
    "unlock_at": "2026-09-23T01:00:00Z",
    "availability": "LOCKED",
    "generation": "NOT_STARTED"
  },
  "report": {
    "unlock_at": "2026-09-23T13:00:00Z",
    "availability": "LOCKED",
    "generation": "NOT_STARTED"
  }
}
```

客户端使用 `server_time` 校准倒计时，不能以本地系统时间决定权限。

---

# 11. Sketch AI Generation

## 11.1 源需求

- 一个邮箱只能生成一次。
- 再次进入展示已保存图片。
- 输入 Q3/Q5/Q6/Q7。
- PRD 写的模型名称：`gpt-image-2-text-to-image`。
- Prompt 使用 PRD 中的 Soulmate Pencil Portrait Prompt。

### OpenAI 实现名称校正

当前 OpenAI 官方 API 的实际 model id 是：

```text
gpt-image-2
```

对应 `POST /v1/images/generations`。

因此：
- 产品文档中的 `gpt-image-2-text-to-image` 可继续作为业务描述。
- 调 OpenAI API 时使用 `gpt-image-2`，除非项目内部 Provider wrapper 明确实现了别名。
- 官方现在还有更新的 GPT Image 2.5 模型，但 V1 不自动升级；模型变化会影响风格、成本与验收，需要产品另行确认。

## 11.2 Input Mapping

```text
Q3 → gender
Q5 → age_range
Q6 → ethnicity
Q7 → features
```

Example：

```json
{
  "gender": "male",
  "age_range": "30-40",
  "ethnicity": "Asian",
  "features": "Kindness"
}
```

## 11.3 Prompt Versioning

```text
prompt_name    = soulmate_pencil_portrait
prompt_version = v1
model          = gpt-image-2
```

每个生成结果必须保存：
- provider
- model
- model snapshot（若使用）
- prompt_version
- normalized inputs
- provider request id
- generation time
- output storage key

## 11.4 触发方式

源 PRD 要求“进入画像页再调用模型”。

因此 V1 默认：

```text
SOULMATE_SKETCH_GENERATION_MODE=on_demand
```

流程：

```text
12h 到达
↓
用户打开 /soulmate/sketch
↓
检查已有完成结果
├─ exists → 直接返回
└─ none
    ↓
  create idempotent job
    ↓
  QUEUED → PROCESSING → COMPLETED
```

为了未来改善“等 12h 后还要继续等生成”的体验，Worker 同时支持：

```text
pre_generate_hidden
```

模式，但默认不启用，除非产品确认偏离原 PRD。

## 11.5 一邮箱一次

数据库层强约束，而不是前端判断：

```text
UNIQUE(email_normalized) WHERE artifact_type = 'SKETCH'
```

如果已有 COMPLETED：
- 不调用模型
- 返回已有 asset

如果已有 PROCESSING：
- 返回当前 job
- 不创建第二个 job

如果 FAILED：
- 使用同一 artifact/job 记录 retry
- 不创建新的“第二份画像”

## 11.6 Job

```json
{
  "job_type": "SOULMATE_SKETCH",
  "idempotency_key": "sketch:<email_hash>:v1",
  "session_id": "...",
  "artifact_id": "...",
  "attempt": 1
}
```

状态：

```text
QUEUED
PROCESSING
COMPLETED
FAILED_RETRYABLE
FAILED_PERMANENT
```

建议 max attempts = 3，指数退避。

## 11.7 Storage

OpenAI 返回的数据生成后立即持久化到自有对象存储。

推荐 key：

```text
soulmate/sketches/{artifact_id}/original.webp
```

不要长期依赖第三方临时 URL。

**[DEV DECISION]** 画面为竖向 portrait，默认 image config 做成环境配置，例如：

```text
SOULMATE_IMAGE_SIZE=1024x1536
SOULMATE_IMAGE_QUALITY=medium
SOULMATE_IMAGE_FORMAT=webp
```

这些是工程默认值，不是 PRD 固定需求。

---

# 12. Sketch Prompt v1

Prompt 内容必须从配置文件加载，例如：

```text
prompts/soulmate-sketch/v1.txt
```

模板变量仅允许：

```text
{gender}
{age_range}
{ethnicity}
{features}
```

Provider 调用前做：
- 变量存在性校验
- option code → 人类可读值映射
- Prompt version hash
- 禁止客户端提交任意 prompt

> 完整 Prompt 以 PRD 原文为 source of truth；开发应直接将 PRD Prompt 迁入版本化模板文件，不在 UI 组件中内嵌。

---

# 13. Soulmate Report

## 13.1 当前已确认

Figma `102:1358` 是 editorial report：
- H1
- intro
- numbered sections
- paragraph
- optional point list
- end mark

PRD 未指定生成模型与 Prompt。

## 13.2 V1 数据结构

```ts
interface SoulmateReportV1 {
  title: string;
  intro: string;
  sections: Array<{
    index: string;
    title: string;
    body: string;
    points?: Array<{
      title?: string;
      body: string;
    }>;
  }>;
  closing?: string;
}
```

数据库保存 `content_json`，前端只负责 renderer，不直接渲染任意模型 Markdown/HTML。

## 13.3 Generator Interface

```ts
interface SoulmateReportGenerator {
  generate(input: {
    profile: SoulmateProfileV1;
    promptVersion: string;
  }): Promise<SoulmateReportV1>;
}
```

正式 Provider：

```text
REPORT_PROVIDER
REPORT_MODEL
REPORT_PROMPT_VERSION
```

均为配置项。

**[TBD REPORT-02]** 正式 AI Prompt/Model 没有源材料支持。Codex 在 V1 可以实现接口、JSON schema、job、renderer 与 mock fixture，但不得自行写一套“灵魂解读”作为生产规则。

## 13.4 Report 时间

```text
report_unlock_at = subscription_success_at + 24h
```

生成策略与 Sketch 同样可配置：

```text
on_demand
pre_generate_hidden
```

V1 如无新产品指令，默认 `on_demand`。

---

# 14. Database Schema (PostgreSQL reference)

> 如果现有项目已有 `users`, `subscriptions`, `payments` 等表，应复用现有模型并添加 Soulmate 外键/metadata，不要复制一套账号与支付系统。以下是独立实现时的参考 DDL。

```sql
CREATE TABLE soulmate_quiz_versions (
  id                uuid PRIMARY KEY,
  version           varchar(64) UNIQUE NOT NULL,
  config_json       jsonb NOT NULL,
  is_active         boolean NOT NULL DEFAULT false,
  created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE soulmate_sessions (
  id                        uuid PRIMARY KEY,
  public_id                 varchar(64) UNIQUE NOT NULL,
  user_id                   uuid NULL,
  email                     varchar(320) NULL,
  email_normalized          varchar(320) NULL,
  quiz_version              varchar(64) NOT NULL,
  status                    varchar(32) NOT NULL,
  current_step              varchar(64) NOT NULL,
  utm_json                  jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now(),
  quiz_completed_at         timestamptz NULL,
  email_captured_at         timestamptz NULL,
  subscription_success_at   timestamptz NULL
);

CREATE INDEX idx_soulmate_sessions_email
  ON soulmate_sessions(email_normalized);

CREATE TABLE soulmate_answers (
  id                uuid PRIMARY KEY,
  session_id        uuid NOT NULL REFERENCES soulmate_sessions(id) ON DELETE CASCADE,
  question_code     varchar(32) NOT NULL,
  answer_json       jsonb NOT NULL,
  first_viewed_at   timestamptz NULL,
  answered_at       timestamptz NOT NULL DEFAULT now(),
  duration_ms       integer NULL,
  updated_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE(session_id, question_code)
);

CREATE TABLE soulmate_profiles (
  id                          uuid PRIMARY KEY,
  session_id                  uuid UNIQUE NOT NULL REFERENCES soulmate_sessions(id) ON DELETE CASCADE,
  profile_version             varchar(32) NOT NULL DEFAULT 'v1',
  user_gender                 varchar(32) NULL,
  preferred_partner_gender    varchar(32) NULL,
  love_life_status            varchar(64) NULL,
  preferred_partner_age_range varchar(64) NULL,
  preferred_partner_ethnicity varchar(128) NULL,
  key_soulmate_quality        varchar(64) NULL,
  birth_date                  date NULL,
  zodiac_sign                 varchar(32) NULL,
  element                     varchar(32) NULL,
  decision_style              varchar(32) NULL,
  personal_challenge          varchar(64) NULL,
  red_flag                    varchar(64) NULL,
  similarity_preference       varchar(64) NULL,
  relationship_dynamic        varchar(64) NULL,
  love_language               varchar(64) NULL,
  connection_style            varchar(64) NULL,
  relationship_fear           varchar(64) NULL,
  life_goals                  jsonb NOT NULL DEFAULT '[]'::jsonb,
  spiritual_person            boolean NULL,
  familiar_psychic_artistry   boolean NULL,
  warning_response            varchar(8) NULL,
  updated_at                  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE subscriptions (
  id                        uuid PRIMARY KEY,
  session_id                uuid NOT NULL REFERENCES soulmate_sessions(id),
  user_id                   uuid NULL,
  provider                  varchar(32) NOT NULL DEFAULT 'paypal',
  provider_subscription_id  varchar(128) UNIQUE NOT NULL,
  provider_plan_id          varchar(128) NOT NULL,
  provider_status           varchar(32) NOT NULL,
  currency                  char(3) NOT NULL,
  intro_price               numeric(12,2) NULL,
  regular_price             numeric(12,2) NOT NULL,
  first_payment_at          timestamptz NULL,
  next_billing_at           timestamptz NULL,
  paid_through_at           timestamptz NULL,
  cancelled_at              timestamptz NULL,
  suspended_at              timestamptz NULL,
  expired_at                timestamptz NULL,
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE subscription_payments (
  id                    uuid PRIMARY KEY,
  subscription_id       uuid NOT NULL REFERENCES subscriptions(id),
  provider_payment_id   varchar(128) UNIQUE NOT NULL,
  provider_event_id     varchar(128) NULL,
  cycle_no              integer NULL,
  amount                numeric(12,2) NOT NULL,
  currency              char(3) NOT NULL,
  status                varchar(32) NOT NULL,
  paid_at               timestamptz NULL,
  refunded_at           timestamptz NULL,
  raw_json              jsonb NULL,
  created_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE paypal_webhook_events (
  id                  uuid PRIMARY KEY,
  paypal_event_id     varchar(128) UNIQUE NOT NULL,
  event_type          varchar(128) NOT NULL,
  resource_id         varchar(128) NULL,
  payload_json        jsonb NOT NULL,
  verified            boolean NOT NULL DEFAULT false,
  processed_at        timestamptz NULL,
  processing_error    text NULL,
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE soulmate_artifacts (
  id                  uuid PRIMARY KEY,
  session_id          uuid NOT NULL REFERENCES soulmate_sessions(id),
  email_normalized    varchar(320) NOT NULL,
  artifact_type       varchar(32) NOT NULL, -- SKETCH | REPORT
  artifact_version    varchar(32) NOT NULL DEFAULT 'v1',
  unlock_at           timestamptz NOT NULL,
  generation_status   varchar(32) NOT NULL DEFAULT 'NOT_STARTED',
  provider            varchar(64) NULL,
  model               varchar(128) NULL,
  prompt_version      varchar(64) NULL,
  input_json          jsonb NULL,
  content_json        jsonb NULL,
  storage_key         text NULL,
  provider_request_id varchar(256) NULL,
  attempt_count       integer NOT NULL DEFAULT 0,
  last_error_code     varchar(128) NULL,
  last_error_message  text NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  generation_started_at timestamptz NULL,
  completed_at        timestamptz NULL,
  updated_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE(session_id, artifact_type, artifact_version)
);

CREATE UNIQUE INDEX uq_soulmate_one_sketch_per_email
ON soulmate_artifacts(email_normalized)
WHERE artifact_type = 'SKETCH';

CREATE TABLE ai_generation_jobs (
  id                 uuid PRIMARY KEY,
  artifact_id        uuid NOT NULL REFERENCES soulmate_artifacts(id),
  job_type           varchar(64) NOT NULL,
  idempotency_key    varchar(256) UNIQUE NOT NULL,
  status             varchar(32) NOT NULL,
  attempt            integer NOT NULL DEFAULT 0,
  run_after          timestamptz NULL,
  locked_at          timestamptz NULL,
  error_json         jsonb NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);
```

---

# 15. Backend API Contract

## 15.1 Session

```http
POST /api/soulmate/sessions
GET  /api/soulmate/sessions/current
```

Create response：

```json
{
  "session_id": "...",
  "quiz_version": "soulmate-quiz-v1",
  "current_step": "transition_0"
}
```

## 15.2 Quiz Config

```http
GET /api/soulmate/quiz/config
```

返回 session 对应的 immutable version。

## 15.3 Answer

```http
PUT /api/soulmate/sessions/:id/answers/:questionCode
```

Single：

```json
{ "value": "intelligence", "duration_ms": 4200 }
```

Multi：

```json
{
  "values": ["traveling_the_world", "personal_growth"],
  "duration_ms": 8100
}
```

Date：

```json
{ "value": "1991-09-10", "duration_ms": 3900 }
```

Response：

```json
{
  "saved": true,
  "next_step": "transition_2"
}
```

**后端必须自行根据 flow config 计算 `next_step`，不能信任客户端传入的 next。**

## 15.4 Interstitial Answers

```http
PUT /api/soulmate/sessions/:id/interstitials/:code
```

Codes：

```text
spiritual_person
familiar_psychic_artistry
warning_response
```

## 15.5 Email

```http
POST /api/soulmate/sessions/:id/email
```

## 15.6 Checkout Config

```http
GET /api/soulmate/subscription/offer
```

Response 示例：

```json
{
  "currency": "USD",
  "intro_price": "{INTRO_PRICE}",
  "regular_price": "{REGULAR_PRICE}",
  "interval": "MONTH",
  "paypal_plan_id": "P-..."
}
```

> 前端可以显示价格，但业务端仍需按服务端选出的 Plan 创建订阅。

## 15.7 PayPal Confirm

```http
POST /api/soulmate/subscription/paypal/confirm

{
  "session_id": "...",
  "paypal_subscription_id": "I-..."
}
```

Backend：
1. 验证 session ownership。
2. `GET /v1/billing/subscriptions/{id}`。
3. 验证 `plan_id` 是允许的 Soulmate plan。
4. 验证 subscriber/session 关系可接受。
5. upsert local subscription。
6. 返回 `PROCESSING`，直到首笔 completed payment。

## 15.8 Subscription Status

```http
GET /api/soulmate/subscription/status
```

前端 payment-processing 页面每 2–3 秒轮询，最长建议 60 秒；超时后显示“Payment confirmation is taking longer than expected”，不要再次创建 subscription。

## 15.9 Cancel

```http
POST /api/account/subscription/cancel
```

流程：
1. Read local subscription.
2. Fetch provider latest status / next billing time.
3. Persist `paid_through_at`.
4. Call PayPal cancel.
5. Wait/accept webhook reconciliation.
6. UI shows no future renewal, access until paid-through date.

## 15.10 Sketch

```http
GET  /api/soulmate/sketch
POST /api/soulmate/sketch/generate
```

`POST`：
- server check unlock
- server check existing artifact
- idempotent queue
- return `202`

## 15.11 Report

```http
GET  /api/soulmate/report
POST /api/soulmate/report/generate
```

同样做 unlock + idempotency。

---

# 16. 前端组件结构

```text
features/soulmate/
  api/
    soulmate-client
    paypal-client
  config/
    routes
    analytics
  components/
    SoulmateShell
    BrandHeader
    QuizProgress
    QuestionTitle
    OptionCard
    SingleChoiceQuestion
    MultiChoiceQuestion
    DateQuestion
    TransitionPage
    InterstitialQuestionModal
    EmailSummary
    Countdown
    ArtifactStatusCard
    SketchViewer
    ReportRenderer
  pages/
    Landing
    Quiz
    Transition
    Email
    Subscribe
    PaymentProcessing
    Result
    Sketch
    Report
  state/
    session-store
  types/
    quiz
    profile
    subscription
    artifact
    report
```

实际框架/目录按现有仓库调整；不要为了本规格强行引入 React/Tailwind。

---

# 17. Backend 模块结构

```text
SoulmateModule
  QuizService
  SessionService
  ProfileBuilder
  TransitionService
  EmailCaptureService
  SoulmateSubscriptionService
  PayPalAdapter
  ResultService
  ArtifactService
  SketchGenerationService
  ReportGenerationService
  GenerationJobWorker
  AnalyticsService
```

第三方能力通过 Adapter 隔离：

```ts
interface PaymentProvider { ... }
interface ImageGenerationProvider { ... }
interface ReportGenerationProvider { ... }
interface ObjectStorageProvider { ... }
```

---

# 18. Analytics

## 18.1 Funnel Events

| Event | Trigger | Key properties |
|---|---|---|
| `soulmate_landing_view` | landing view | source, campaign |
| `soulmate_start_click` | Let's begin | session_id |
| `soulmate_login_click` | Login | session_id |
| `soulmate_transition_view` | transition | step |
| `soulmate_transition_continue` | continue | step |
| `soulmate_quiz_started` | first question | quiz_version |
| `soulmate_question_view` | each q | question_code |
| `soulmate_question_answered` | save success | question_code, option_code(s), duration_ms |
| `soulmate_quiz_back` | back | from_q, to_q |
| `soulmate_quiz_completed` | q18 done | total_duration |
| `soulmate_interstitial_answered` | popup | code, value |
| `soulmate_email_view` | email page | partner_gender |
| `soulmate_email_submitted` | saved | domain_type only / no raw email |
| `soulmate_subscribe_view` | subscribe page | intro_price, regular_price, currency |
| `soulmate_paypal_start` | PayPal start | plan_id |
| `soulmate_paypal_approved` | client approval | subscription_id |
| `soulmate_payment_confirmed` | first completed payment | amount, currency |
| `soulmate_payment_failed` | failure | reason_code |
| `soulmate_result_view` | result | sketch_availability, report_availability |
| `soulmate_sketch_unlocked` | first unlocked view | hours_since_payment |
| `soulmate_sketch_generation_started` | job | model, prompt_version |
| `soulmate_sketch_generation_completed` | job | latency_ms, attempts |
| `soulmate_sketch_generation_failed` | job | error_code, attempts |
| `soulmate_sketch_viewed` | final view | artifact_version |
| `soulmate_report_unlocked` | unlocked | hours_since_payment |
| `soulmate_report_viewed` | report view | report_version |
| `soulmate_subscription_cancelled` | cancel | provider_status |

## 18.2 Analytics Privacy

- 不发送 raw email 到第三方分析系统。
- 用内部匿名 `session_public_id` / `user_id`。
- 题目传 option code，不传自由文本。
- DOB 默认不作为 analytics property；如需年龄段必须由服务端派生。

---

# 19. Error Handling & Observability

## 19.1 必须有结构化日志

字段：

```text
request_id
session_id
user_id nullable
paypal_subscription_id nullable
artifact_id nullable
job_id nullable
provider_request_id nullable
event_type
error_code
latency_ms
```

## 19.2 Alert

P1：
- PayPal webhook 连续验签失败。
- Payment completed 但 session 未能激活。
- Sketch generation failure rate 超阈值。
- Storage upload failure。

P2：
- Quiz answer API error rate。
- Payment confirmation 超时增加。
- Report generation backlog。

## 19.3 不向用户显示 provider 原始错误

例如：
- `OPENAI_429` → “Your portrait is taking a little longer than expected.”
- `PAYPAL_5XX` → “We’re still confirming your payment.”

内部保留原始 code/debug id。

---

# 20. Security / Privacy

- PayPal client secret / OpenAI API key 仅服务端。
- Webhook 使用 raw body 验签。
- 所有 Soulmate 资源都校验 session/user ownership。
- 客户端不能修改：
  - `subscription_success_at`
  - `unlock_at`
  - `provider_status`
  - `generation_status`
  - `storage_key`
- 防止 IDOR：不允许通过猜测 artifact id 读取他人画像。
- 对象存储建议 private bucket + signed URL，或经过受控 CDN。
- Email 为 PII，遵循现有隐私政策与删除流程。
- 支付卡数据不进入本系统，由 PayPal 承担支付界面。
- Prompt 与模型输出需要记录版本，不记录不必要的支付敏感信息。

---

# 21. Marketing/Compliance Gate

源 PRD 把订阅页中的四条 testimonial 明确标记为“假评价”。这些内容**不得作为真实消费者评价直接上线**。

开发可以实现：

```text
<TestimonialCarousel items={cmsTestimonials} />
```

但 production CMS 只能放：
- 真实、授权、可追溯的用户评价；或
- 明确标识为示例/演示的非用户陈述。

同理，Figma Landing 中看到的 `3M+ sketches created`、`18K+ 5 star reviews` 等数字，上线前必须有可证明来源；否则应替换/隐藏，而不是写死。

订阅页必须明确披露：
- 今天扣款金额。
- 第二个月起月费。
- 自动续费。
- 取消方式。

---

# 22. Environment / Configuration

```env
APP_BASE_URL=

# Soulmate
SOULMATE_QUIZ_VERSION=soulmate-quiz-v1
SOULMATE_SKETCH_UNLOCK_HOURS=12
SOULMATE_REPORT_UNLOCK_HOURS=24
SOULMATE_SKETCH_GENERATION_MODE=on_demand
SOULMATE_REPORT_GENERATION_MODE=on_demand

# PayPal
PAYPAL_ENV=sandbox
PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
PAYPAL_WEBHOOK_ID=
PAYPAL_PRODUCT_ID=
PAYPAL_SOULMATE_INTRO_PLAN_ID=
PAYPAL_SOULMATE_STANDARD_PLAN_ID=   # optional until eligibility policy exists

SOULMATE_CURRENCY=USD
SOULMATE_INTRO_PRICE=
SOULMATE_REGULAR_PRICE=

# OpenAI
OPENAI_API_KEY=
SOULMATE_IMAGE_MODEL=gpt-image-2
SOULMATE_IMAGE_SIZE=1024x1536
SOULMATE_IMAGE_QUALITY=medium
SOULMATE_IMAGE_FORMAT=webp
SOULMATE_SKETCH_PROMPT_VERSION=v1

# Report
SOULMATE_REPORT_PROVIDER=
SOULMATE_REPORT_MODEL=
SOULMATE_REPORT_PROMPT_VERSION=

# Storage
OBJECT_STORAGE_BUCKET=
OBJECT_STORAGE_REGION=
OBJECT_STORAGE_ENDPOINT=
OBJECT_STORAGE_ACCESS_KEY=
OBJECT_STORAGE_SECRET_KEY=
```

生产价格的 source of truth 推荐同时校验 PayPal Plan，不能只信 `.env` 显示值。

---

# 23. Test Plan

## 23.1 Unit

### Zodiac
必须覆盖每个边界：

```text
03-20 Pisces
03-21 Aries
04-19 Aries
04-20 Taurus
...
12-20 Sagittarius
12-21 Capricorn
01-20 Capricorn
01-21 Aquarius
02-19 Aquarius
02-20 Pisces
02-29 Pisces
```

### Quiz
- Single 只能一个 value。
- Multi 去重。
- Multi 至少 1 个。
- 非法 option code 返回 4xx。
- q03 与 q02 不串字段。
- Back 恢复答案。
- Version 不漂移。

### Payment
- duplicate webhook。
- out-of-order webhook。
- PAYMENT.SALE.COMPLETED 先于 ACTIVATED。
- failed payment 不激活 entitlement。
- refund/reversal 可正确入账。
- client forged success 无效。

### Artifacts
- 12h 前拒绝 Sketch。
- 24h 前拒绝 Report。
- 同邮箱并发两个 generate 请求只创建一个 job。
- completed 后 generate 不再次调用模型。
- retry 不创建第二个 artifact。

## 23.2 Integration

PayPal Sandbox：
1. Create/approve subscription。
2. 收到 CREATED/ACTIVATED。
3. 收到首笔 PAYMENT.SALE.COMPLETED。
4. result unlock 时间正确。
5. Sandbox recurring payment event 可入账。
6. cancel。
7. failed payment / suspension。
8. webhook duplicate replay。

OpenAI：
- valid prompt。
- timeout。
- 429。
- 5xx。
- invalid output。
- storage failure。

## 23.3 E2E

### Happy Path
```text
Landing
→ Transition-0
→ 完成 Q2-Q18
→ Transition-5 modals
→ Email
→ Subscribe
→ PayPal approval
→ first payment confirmed
→ Result
→ time travel / test override +12h
→ Sketch generation
→ persisted sketch
→ +24h
→ Report
```

### Recovery
- Q9 时刷新。
- Email 页关闭后再开。
- PayPal approved 后浏览器关闭。
- Webhook 到达后重新打开 result。
- Sketch 处理中刷新。
- Sketch completed 后换 tab / 再进入。

---

# 24. API Acceptance Criteria

## Quiz
- [ ] Excel 17 题全部存在且顺序一致。
- [ ] Single 点击即提交并跳转。
- [ ] Multi 未选时按钮 disabled。
- [ ] Q8 DOB 可恢复。
- [ ] Q8→zodiac 全边界正确。
- [ ] Q10 三种 copy 正确。
- [ ] 所有回答可刷新恢复。

## Email
- [ ] Q3 male/female 视觉正确。
- [ ] Q3/Q5/Q6 摘要正确。
- [ ] Email server-side validate。
- [ ] 不把 email 当成已验证登录身份。

## PayPal
- [ ] 首月优惠 cycle + regular monthly cycle 正确。
- [ ] 页面明确显示续费价格。
- [ ] `onApprove` 不直接激活权益。
- [ ] 首个 `PAYMENT.SALE.COMPLETED` 才产生 `subscription_success_at`。
- [ ] Webhook 验签。
- [ ] Webhook 幂等。
- [ ] Payment rows 可追账。
- [ ] Cancel 不删除已生成内容。

## Result
- [ ] 12h/24h 都以服务端时间为准。
- [ ] 修改客户端时钟不能提前访问。
- [ ] locked/ready/generating/completed/failed UI 完整。

## Sketch
- [ ] 使用 Q3/Q5/Q6/Q7。
- [ ] 实际 OpenAI model id `gpt-image-2`。
- [ ] Prompt v1 版本化。
- [ ] 一个 email 只有一份 Sketch。
- [ ] 生成失败可 retry。
- [ ] 结果存自有对象存储。
- [ ] 再次进入不重新生成。

## Report
- [ ] 结构化 JSON renderer。
- [ ] 24h guard。
- [ ] 未定义的 AI Prompt 不硬编码上线。

---

---

# 25. External Technical References

### PayPal

- Subscriptions overview: https://developer.paypal.com/subscriptions/about/
- Discounted/free trial cycle: https://developer.paypal.com/subscriptions/trial-period/
- Customize subscriptions: https://developer.paypal.com/subscriptions/customize
- Subscription webhooks: https://developer.paypal.com/subscriptions/webhooks/
- Show subscription: https://developer.paypal.com/api/subscriptions/v1/subscriptions-get/
- Cancel subscription: https://developer.paypal.com/api/subscriptions/v1/subscriptions-cancel/
- Webhook integration/verification: https://developer.paypal.com/api/rest/webhooks/rest/

### OpenAI Image API

- GPT Image 2 model: https://developers.openai.com/api/docs/models/gpt-image-2
- Image generation guide: https://developers.openai.com/api/docs/guides/image-generation
- Image generation endpoint: https://developers.openai.com/api/reference/resources/images/methods/generate

---

---

# 26. Definition of Done

Soulmate Path V1 可以被定义为完成，当且仅当：

- [ ] Figma 核心页面在移动端达到视觉验收。
- [ ] Excel 17 个 Quiz step 与答案值全部可追踪、可恢复。
- [ ] Q2/Q3 语义不会混淆。
- [ ] Zodiac 和 Transition-3 正确。
- [ ] PayPal 首月优惠 + 后续月费在 Sandbox/Production plan 中正确。
- [ ] 首笔支付由 Webhook 确认，不能伪造。
- [ ] Webhook 验签 + 幂等 + payment ledger 完成。
- [ ] 12h/24h 服务端倒计时完成。
- [ ] Sketch `gpt-image-2` 生成、重试、保存、唯一性完成。
- [ ] Report schema/renderer 完成；正式 AI 内容只在 Prompt 通过产品确认后开启。
- [ ] Drawer/Settings 正确反映状态。
- [ ] Analytics 能还原 Landing → Payment → Sketch funnel。
- [ ] 所有 P0/P1 QA case 通过。
- [ ] Production 不包含虚假 testimonial 或无依据统计数字。
- [ ] 所有 DONE Task 均有 `docs/handoffs/<TASK-ID>.md`。
- [ ] M1–M6（适用范围）均有对应 Review Artifact，最终生产 Gate 为 PASS。
- [ ] `PROJECT-STATE.md` 与实际仓库/发布状态一致。
- [ ] 所有生产阻塞 TBD 已在 `DECISIONS.md` 关闭或明确批准为非阻塞。

---

**End of `Soulmate-Path-DEV-SPEC-v1.2`**
