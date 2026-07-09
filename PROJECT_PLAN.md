# 炼真（Albedo）项目计划

> 当前版本：**v0.1.0（MVP：验真假核心闭环）**
> 蓝图：见 `BLUEPRINT.md` ｜ 调研报告：见 `docs/ALBEDO-RESEARCH-2026-07-09.md`
> 最后更新：2026-07-09

---

## 一、竞品借鉴地图（MVP 每个能力从哪来）

我们不做重复造轮子——能借鉴的成熟方法直接拿来，只在「独特之处」下功夫。

| 我们的能力（MVP） | 借鉴自竞品 / 研究 | 我们的独特处理 |
|---|---|---|
| **质量评估（多维）**（真实性 + 文案 + 结构 + 逻辑 分维度） | **nuwa-skill** 三重验证 + **anyone-skill** L1-L4 证据分级 + **OpenFactCheck** 统一核查管线 + **统计学手段**（跨源共识频率 / 数值自洽 / 离群检测） | 单源 LLM 实现真实性维度；**统计学**为补充验证（MVP 轻量数值自洽，规模期跨源共识）；输出直接映射熔知 `epistemic_status` |
| **优点分析**（6 子能力） | **skill-from-masters**（方法萃取，非人物萃取）+ **nuwa**（诚实边界=陷阱预警）+ **pangu**（质量验证审计） | **多 SOP 并列产出**（对齐 Rubedo 可消费格式） |
| **结构化提炼**（标准 SOP） | **TubeScribed**（商业化 SOP 格式：目的+前置+编号步骤+警告+完成清单） | 产出对齐 **Rubedo 可消费格式**，直接进凝华 SOP 建立 |
| **溯源** | 所有竞品均有来源记录 | 与 Nigredo `video_id` / 时间戳**强绑定**（精炼阶段即知来源） |
| **内容净化**（去广告） | **pangu** 质量验证中的净化环节 | 内置「卖课话术特征模式库」（过度承诺/模糊施压/付费诱导） |
| **信任聚合 FPF** | **熔知移交**（非竞品，原属 Citrinitas 远期待办） | 独特：从熔知移交，作为 Albedo 核心能力 |

**不重复造的部分**：事实核查底层（OpenFactCheck 管线）、证据分级（anyone-skill L1-L4）规模期直接接入，MVP 先用 LLM 单源启发式实现。

---

## 二、我们的独特之处（护城河种子）

这是竞品都没有、或做不到的，MVP 起就要埋下种子：

1. **流水线中段定位（非端到端单人工具）**
   pangu / nuwa / dalio 都是「自己采、自己炼、自己存、自己产 skill」的端到端工具。Albedo 只做**认知精炼中段**，对接 Nigredo（采集）→ Citrinitas（存储）→ Rubedo（变现）。这是本质差异，也避免重造轮子。

2. **平台无关的认知精炼 + 文本类型感知**
   竞品多绑死单一采集源（如某站视频）。Albedo 只吃「文字」——Nigredo 产出的生料文本，不绑任何平台（B站 / YouTube / 公众号 / 小红书 等皆可）。未来任何来源的文字都能炼，天然适配你多业务线、多采集源的格局。但文字有「类型」之分：口语字幕（零碎、无段落）与条理清晰的文案（小红书笔记、文章）处理方式不同——Albedo 用 `text_type` 标记区分，按类型调整净化与评估策略，不绑平台但认文本类型。平台元数据（播放量/受众/互动）由 Nigredo 归一化为统一信号包传入，Albedo 只吃归一化信号。

3. **多 SOP 并列产出，对接 Rubedo**
   竞品产出「可安装 Skill」；Albedo 产出「**可被执行的标准 SOP**」，直接进凝华（Rubedo）的 SOP 建立环节——贴合你「多个 SOP 并列进行」的工作方式。

4. **跨源矛盾检测（规模期独门空间）**
   单人蒸馏无矛盾可检，单条事实核查不跨源比经验。Albedo 未来做「多教程互相印证 / 冲突仲裁」——竞品的空白区。

5. **FPF 信任聚合（熔知移交）**
   从熔知移交的核心能力，竞品无对应物。

6. **产出双用 + 引用 / 变现标注（贴合一人公司主理人）**
   炼真成果既是机器可入库的结构化对象，也是说人话的鉴定报告——主理人直接读、直接决策，不绕弯。报告醒目标出"是否涉及变现"（卖课/带货/工具付费）与"引用了哪些书/网址"——市面事实核查器只给真假分、不给经营视角的标注，这是 Albedo 对主理人独有的体贴。

---

## 三、版本路线

| 版本 | 目标 | 关键能力 |
|---|---|---|
| **v0.1.0（当前）** | MVP 验真假核心闭环 | 内容净化（按文本类型：字幕 ASR 清洗 / 结构化文案直提炼）+ 质量评估**真实性维度**（大模型 + 轻量统计数值自洽）；先跑通单条最小可用 |
| v0.2.0 | 完整多维鉴定报告 + 批量 | 质量评估补全**文案/结构/逻辑**维度 + 优点分析（6 子能力）+ 结构化 SOP + 溯源 + **引用标记(references)** + **变现标注(monetization)** + **人类可读报告渲染(report)** + 批量/队列并行处理 |
| v0.3.0 | 验真假深化（规模期） | 跨源矛盾检测 + 跨源共识统计 + 时效判定 + 冲突仲裁（基础验真假已稳，规模期一次做实） |

> 注：原「v0.3.0 业务线适配评估」已移出 Albedo——4 条业务线适配度评分归凝华（Rubedo）SOP 建立 / 总指挥部（OpusMagnum）编排；Albedo 只产出通用 SOP 与适用场景标签，不做生意适配评分。
> 注（续）：输入源未来将扩展「网页」(`text_type=webpage`)，抓取由适配器完成，炼真仍只吃文字；与熔知 v1.5.0「网页 URL 直接摄入」的边界见 BLUEPRINT「将来会做」。

---

## 四、任务清单（按版本分组）

> 原则：每个任务对应 FLOWCHART 节点；MVP 只做单源闭环；竞品已有成熟方法的用 LLM 启发式快速实现，不为 MVP 自建复杂管线。

### v0.1.0 验真假核心闭环 [MVP必须]

- **T1** 数据契约 `core/models.py`：定义 `AlbedoInput`（对齐 Nigredo `process()` 输出：text / **text_type** / **signals** / video_id / title / up_name / source_url）+ `RefinedKnowledgeObject`（**quality 从一开始设计成多维对象** truthfulness/copywriting/structure/logic，v0.1.0 先填 truthfulness + status）📍C1/C7
- **T2** 内容净化 `core/purify.py`：按 `text_type` 处理（字幕走 ASR 清洗去语气词/纠错，结构化文案直提炼）+ 去广告话术（卖课特征模式库）+ 多语言翻译占位 📍C2
- **T3** 质量评估 `core/assess.py`：LLM 单源评估**真实性维度** → `truthfulness.label(真/假/可疑)` + `reasoning`；借鉴 nuwa 三重验证 + anyone-skill 证据分级；**统计学手段**（数值自洽）作为补充验证；同步检测 `monetization.related`（复用卖课话术特征） 📍C3
- **T7** 流水线编排（最小）`flows/refine.py`：串联 C2→C3，组装最小 `RefinedKnowledgeObject`，由 quality.label 推 status 📍C1→C7
- **T8** LLM 调用封装 `core/llm.py`：对齐熔知 `_call_llm_api`（DeepSeek，env 配置 base_url/api_key/model），供 C3 复用 📍C3
- **T9** 最小 UI `app.py` + `run.bat`：粘贴文本（或选 Nigredo 输出 JSON）→ 一键炼真 → 展示「真假鉴定」📍C7

### v0.2.0 完整鉴定报告 + 批量 [MVP延伸]

- **T4** 优点分析 `core/merit.py`：LLM 结构化输出 6 子能力（核心洞察 / 可复用步骤 / 差异化亮点 / 适用场景 / 陷阱预警 / 迁移成本）；借鉴 skill-from-masters + nuwa 诚实边界 📍C4
- **T5** 结构化提炼 `core/structure.py`：产出标准 SOP（目的 + 前置条件 + 编号步骤 + 警告 + 完成清单），对齐 TubeScribed 格式 📍C5
- **T6** 溯源 `core/provenance.py`：从 Nigredo `info` 取 video_id / up_name / source_url / title + 记录 processed_at 📍C6
- **T7+** 流水线补全 `flows/refine.py`：扩展编排串入 C4→C6，补全 `RefinedKnowledgeObject` 全字段（merits / sop / provenance）+ FPF 轻量 trust_score 📍C1→C7
- **T11** 批量 / 队列（方案A）：参考 Nigredo 队列机制，支持多条生料并行炼真 📍C1
- **T12** 鉴定报告产出 `core/report.py`：炼真的**主交付物**——从内部 `RefinedKnowledgeObject` 渲染人能直接看的 Markdown 鉴定报告（v0.1.0 最小版由 T9 UI 直出，v0.2.0 完整版含全维度 + 引用 + 变现标注）；结构化 JSON 仅留作内部/未来入库用 📍C7
- **T13** 引用标记 `core/references.py`：抽取书/网址/资料并结构化 `references` 📍C5

### 已移出 Albedo（归其它项目）

- ~~业务线适配度评分（原 T10）~~：归凝华 Rubedo SOP 建立 / 总指挥部 OpusMagnum 编排；Albedo 仅在 T4「适用场景」产出通用标签，不做生意适配评分。

---

## 五、数据契约（精炼知识对象）

```python
# core/models.py（MVP 字段，规模期扩展不破坏兼容）
AlbedoInput:
  text: str            # 净化前生料（Nigredo subtitle.full_text）
  text_type: str       # 文本类型: "subtitle"|"social_post"|"article"|"doc_ppt"|"doc_excel"|"webpage" —— 决定净化/评估策略（webpage 为未来输入源，抓取由适配器完成）
  signals: dict = {}   # 平台归一化信号包(engagement/audience/sentiment)，Nigredo 归一化传入
  video_id: str = ""   # Nigredo info.bvid
  title: str = ""      # Nigredo info.title
  up_name: str = ""    # Nigredo info.owner.name
  source_url: str = ""

RefinedKnowledgeObject:
  input_ref: AlbedoInput
  clean_text: str                          # C2 净化后
  quality:
    truthfulness: { label: "true"|"false"|"suspect",
                    score: 0-100,
                    reasoning: str,
                    evidence_grade: "L1"|"L2"|"L3"|"L4" }   # 维度① 真实性(驱动 status)
    copywriting:  { score: 0-100, reasoning: str }         # 维度② 文案质量
    structure:    { score: 0-100, reasoning: str }         # 维度③ 结构
    logic:        { score: 0-100, reasoning: str }         # 维度④ 逻辑
  merits: { core_insight: str,
            reusable_steps: [str],
            differentiation: str,
            applicable_scenarios: [str],
            pitfalls: [str],
            migration_cost: str }          # C4
  sop: { purpose: str,
         preconditions: [str],
         steps: [{idx: int, text: str}],
         warnings: [str],
         completion_checklist: [str] }     # C5
  provenance: { video_id, up_name, source_url, title, processed_at }  # C6
  trust_score: float        # 0-1，FPF 轻量版
  status: "accepted"|"suspect"|"rejected"  # 由 quality.truthfulness.label 推
  monetization: { related: bool,
                  category: "selling_course"|"ecommerce"|"tool_paid"|"other"|"",
                  note: str }      # 变现相关标注（内容"在卖什么"的客观属性，非业务线适配评分）
  references: [ { type: "book"|"url"|"video"|"other",
                  value: str,
                  context: str } ]  # 引用标记（书/网址/资料）
  report: str            # 人类可读鉴定报告(Markdown) —— 炼真对外主交付物；结构化字段为其内部表示
```

**下游映射（交熔知时）**：`quality.label` → `epistemic_status`（true→corroborated / suspect→unverified / false→rejected）；`trust_score` → 熔知 payload `trust_score`；`clean_text` 交熔知做分面分类 + 切块 + 向量化 + 入库。

> 版本填充节奏：v0.1.0 仅填 `clean_text` / `quality.truthfulness` / `status` / `monetization.related`（**数据模型从一开始就设计成多维 + 以报告为主交付物**，避免 v0.2.0 推倒重来）；v0.1.0 最小报告由 T9 UI 直出；v0.2.0 补全 `quality.copywriting / structure / logic` + `merits` / `sop` / `provenance` / `trust_score` + `references` + `monetization` 全字段 + `report` 完整渲染。`business_line_tags` 已移除（业务线适配评分移出 Albedo）。

---

## 六、技术选型（MVP）

- **语言**：Python 3.13（对齐 Nigredo / Citrinitas 管理环境）
- **LLM**：DeepSeek，封装复用熔知 `_call_llm_api` 约定（env: `KB_LLM_BASE_URL` / `KB_LLM_MODEL` / `KB_LLM_API_KEY`）
- **UI**：Streamlit（与 Nigredo 一致，双击 run.bat 启动）
- **存储**：`data/out/<video_id>.json`（本地落盘，未来经 API 交熔知）
- **结构化输出**：LLM 输出严格 JSON（借鉴熔知 `_extract_json_block` 解析方式）
- **不引入**：向量库 / 复杂编排框架（MVP 单源顺序管线足够）

---

## 七、验收标准（MVP）

1. 丢一条各平台经验文字（字幕或结构化文案均可，当前以 B站 为主，或选 Nigredo 输出 JSON）→ 一键炼真 → 出一份**多维鉴定报告**（真实性评分 + 文案/结构/逻辑维度 + 核心优点 + 可照搬步骤 + 溯源）；报告醒目标注是否涉及变现、列出引用的书/网址；报告既能在界面看、也能导出 .md 直接给人读
2. 卖课谎言类内容能被标「可疑 / 虚假」并附理由
3. 产出 SOP 能被 Rubedo 直接读取消费（格式对齐）
4. 产出落 `data/out/<id>.json`（结构化，交熔知）+ `报告.md`（人类可读，直接给人看），字段符合第五节契约

---

## 八、竞品参考来源

- pangu-skill（盘古）：端到端人物/领域蒸馏，含质量验证审计
- nuwa-skill（女娲）：5 层认知提取 + 三重验证 + 保真度评分卡
- dalio-skill / skill-from-masters / colleague-skill / anyone-skill / immortal-skill / wisdom-council：人格/方法论蒸馏赛道
- OpenFactCheck：统一事实核查框架（Factcheck-GPT / RARR / Factool）
- TubeScribed：商业化「视频→标准 SOP」工具
- awesome-distill-skills / awesome-persona-skills：赛道精选列表（20+/54+ 项目）
- **（2026-07-09 补）多维/统计/信号/商业核查参照**：TruthfulnessEval / AIGVQA（多维质量）；Acrolinx / Writer / Grammarly / ETS e-rater（写作质量多维）；NumTemp / Cross-Document Fact Verification（统计验真）；Viblio（视频可信度信号，须加「互动≠证据」护栏）；Logically / FactBox.ai / iWeaver / Winston AI / FactSnap（商业单维事实核查器，仅作真实性一维参照）

> 详见 `docs/ALBEDO-RESEARCH-2026-07-09.md` 第十一节竞品全景分析。
