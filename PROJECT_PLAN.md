# 炼真（Albedo）项目计划

> 当前版本：**v0.1.0（MVP：验真假核心闭环）**
> 蓝图（定位/边界）：见 `BLUEPRINT.md` ｜ 调研报告：见 `docs/ALBEDO-RESEARCH-2026-07-09.md`
> 决策记录：见 `docs/ADR-002 ~ ADR-005`
> 最后更新：2026-07-09

---

## 阅读导航（本文逻辑）

```
一、项目定位与边界        —— 炼真是什么、在五器哪、不做什么
二、设计依据              —— 为什么这么定（借鉴谁 + 护城河）
三、主线演进路线（多步）  —— 7 版本 / 6 阶段逻辑推进（核心→跨源→可靠→智能→多模态→合体）
四、任务清单              —— 对齐路线，当前版本具体任务（v0.1/v0.2 已可写码）
五、设计基础              —— 数据契约 / 技术选型 / 验收 / 竞品来源（支撑主线落地）
六、研究课题与版本映射    —— 22 项未来课题，逐项落入目标版本（已在计划中排期）
七、决策记录索引          —— ADR-002~005 一句话 + 文件
```

> **本文两条主线分明**：第三~五节是「已排期的主线计划」（含远期版本）；第六节是「研究课题明细」，每项都标注了**目标版本**，与第三节路线一一对应，不脱离计划。

---

## 一、项目定位与边界

**炼真是什么**：一人公司知识流水线「认知精炼层」——把各平台采来的生料文字，炼成「说人话的鉴定报告」（真假 + 多维质量 + 优点 + 可照搬步骤 + 溯源 + 引用 + 变现标注），并内嵌熔知入库元数据。

**在五器里的位置**（流水线中段）：
```
Nigredo(馏析·采集) → Albedo(炼真·认知精炼) → Citrinitas(熔知·存储) → Rubedo(凝华·变现)
                         ↑ 本计划范围
```

**边界（明确不做什么）**：
- 不采集（归 Nigredo，按「一对象一适配器」抽文字）
- 不存储（归 Citrinitas，炼真只内嵌入库元数据，不落知识库）
- 不变现（归 Rubedo，炼真只标注「内容在卖什么」，不做生意）
- 不做业务线适配评分（归 Rubedo / OpusMagnum；炼真只产通用 SOP + 适用场景标签）
- 不重写意图、不封装产品

**当前重心**：v0.1.0 验真假核心闭环（先把「单条内容能不能信」跑通）。

---

## 二、设计依据（为什么这么定）

### 2.1 竞品借鉴地图（MVP 每个能力从哪来）

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

### 2.2 我们的独特之处（护城河种子）

这是竞品都没有、或做不到的，MVP 起就要埋下种子：

1. **流水线中段定位（非端到端单人工具）**
   pangu / nuwa / dalio 都是「自己采、自己炼、自己存、自己产 skill」的端到端工具。Albedo 只做**认知精炼中段**，对接 Nigredo（采集）→ Citrinitas（存储）→ Rubedo（变现）。这是本质差异，也避免重造轮子。

2. **平台无关的认知精炼 + 文本类型感知**
   Albedo 只吃「文字」——Nigredo 产出的生料文本，不绑任何平台（B站 / YouTube / 公众号 / 小红书 等皆可）。但文字有「类型」之分：口语字幕（零碎、无段落）与条理清晰的文案（小红书笔记、文章）处理方式不同——Albedo 用 `text_type` 标记区分，按类型调整净化与评估策略。平台元数据（播放量/受众/互动）由 Nigredo 归一化为统一信号包传入，Albedo 只吃归一化信号。

3. **多 SOP 并列产出，对接 Rubedo**
   竞品产出「可安装 Skill」；Albedo 产出「**可被执行的标准 SOP**」，直接进凝华（Rubedo）的 SOP 建立环节——贴合「多个 SOP 并列进行」的工作方式。

4. **跨源矛盾检测（规模期独门空间）**
   单人蒸馏无矛盾可检，单条事实核查不跨源比经验。Albedo 未来做「多教程互相印证 / 冲突仲裁」——竞品的空白区。

5. **FPF 信任聚合（熔知移交）**
   从熔知移交的核心能力，竞品无对应物。

6. **入库就绪的人读报告 + 引用 / 变现标注（贴合一人公司主理人）**
   炼真只对外交付**一份说人话的鉴定报告**（Markdown）——主理人直接读、直接决策（ADR-004：不另维护「结构化 JSON + 报告」双输出）。报告内嵌「入库元数据」块（`ingestion_meta`），**预填熔知入库所需的全部分面字段**，熔知入库直读直存（ADR-005）。报告醒目标出「是否涉及变现」与「引用了哪些书/网址」，是市面事实核查器没有的经营视角标注。

---

## 三、主线演进路线（多步逻辑推进）

**推进逻辑（6 个阶段，逐级依赖、不跳步）**：

| 阶段 | 版本 | 目标 | 关键能力 | 对应研究课题 |
|---|---|---|---|---|
| **① 核心闭环**（现在做） | **v0.1.0（当前）** | 验真假核心闭环 | 内容净化（按文本类型）+ 质量评估**真实性维度**（大模型 + 轻量统计数值自洽）；单条最小可用先跑通 | 变现≠差内容护栏（报告注记起步） |
| | **v0.2.0** | 完整多维鉴定报告 + 批量 | 质量评估补全**文案/结构/逻辑**维度 + 优点分析（6 子能力）+ 结构化 SOP + 溯源 + 引用标记 + 变现标注 + 报告渲染 + 批量/队列 + **入库就绪(ingestion_meta)** | — |
| **② 跨源规模**（积累多条来源后） | **v0.3.0** | 验真假深化 | 跨源矛盾检测 + 跨源共识统计 + 时效判定 + 冲突仲裁 + 领域上下文（防域内外误伤）+ 全新说法标「未印证」 | 域内外误伤 / 全新说法无处印证 / 过时SOP / 多冲突SOP |
| **③ 可靠性与可信** | **v0.4.0** | 进料与可解释增强 | 去重/近重复 + 超长切块 + **可解释到根因** + **评测集** + 评分主观偏见注记 + 采不到内容标注（消费 Nigredo 标记） | 去重 / 超长切块 / 可解释到根因 / 评测集 / 评分主观偏见 / 采不到内容标注 |
| **④ 智能维度与经营闭环** | **v0.5.0** | 智能维度 + 经营闭环 | **新颖度维度** + **上手门槛维度** + 变现≠差内容护栏（深化）+ 人肉覆盖（一键「我信这个」）+ 批量总览看板 + 成本账 + 反馈回路（记住你的纠正） | 新颖度 / 上手门槛 / 变现护栏深化 / 人肉覆盖 / 总览看板 / 成本账 / 反馈回路 |
| **⑤ 多模态与深度验证** | **v0.6.0** | 多模态 + 引用深度核验 | 图信息/OCR 提取 + 伪造证据（假图/深度伪造）检测 + 引用未核实核验 + 软广识别 | 图里信息丢失 / 伪造证据 / 引用未核实 / 软广识别 |
| **⑥ 五器合体**（产品化） | **v1.0.0** | 与五器集成 | 接 Nigredo 网页/更多适配器 + 接 Rubedo 闭环验证 SOP（真跑通验证）+ 接 OpusMagnum 编排 + 业务线适配（归彼，炼真供通用标签） | SOP 未验证（与 Rubedo 闭环） / 业务线适配（归彼） |

**每版为什么这个顺序**：
- **v0.1→v0.2**：先稳「单条能不能信」，再在已信的基础上补「多维质量 + 优点 + SOP + 批量 + 入库」——不跳步，最小可用先跑通。
- **v0.3 跨源**：矛盾检测/共识统计/仲裁**没有多条来源无从做起**，故必须等 v0.2 积累够来源才做，放规模期。
- **v0.4 可靠**：跨源之前先让单条结果「可信可控」——去重省钱、切块保准、可解释到根因让你敢信、评测集证明它判得对。
- **v0.5 智能闭环**：在可信基础上加「对你有用的维度」（新颖度/门槛）+ 经营闭环（总览/成本/反馈），让炼真越用越准、越用越省心。
- **v0.6 多模态**：文字之外的图/伪造/引用深度核验，依赖上游多模态能力，放较后。
- **v1.0 合体**：等炼真自身能力稳了，再接进五器总装配，不做早了就是过度设计。

> 注：原「v0.3.0 业务线适配评估」已移出 Albedo——4 条业务线适配度评分归凝华（Rubedo）SOP 建立 / 总指挥部（OpusMagnum）编排；v1.0.0 仅「供通用标签 + 接编排」，不做生意适配评分。
> 注（续）：输入源未来将扩展「网页」(`text_type=webpage`)，抓取由适配器完成，炼真仍只吃文字；与熔知 v1.5.0「网页 URL 直接摄入」的边界见 BLUEPRINT「将来会做」。

---

## 四、任务清单（对齐路线）

> 原则：每个任务对应 FLOWCHART 节点；MVP 只做单源闭环；竞品已有成熟方法的用 LLM 启发式快速实现，不为 MVP 自建复杂管线。
> v0.3.0 之后的任务待进入该版本时再逐条拆解（路线与课题已锁定，见第三/六节）。

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
- **T14** 入库元数据预填 `core/ingest_meta.py`：由精炼结果推导并写入 `ingestion_meta`（content_type / domain UDC / temporal_nature / epistemic_status / trust_score / knowledge_type / target_platform / language / is_personal / access_level 等），对齐熔知分面分类法重构（UDC 9 主类 / temporal_nature / epistemic_status），使熔知入库直读直存 📍C7

### 已移出 Albedo（归其它项目，不列为任务）

- ~~业务线适配度评分（原 T10）~~：归凝华 Rubedo SOP 建立 / 总指挥部 OpusMagnum 编排；Albedo 仅在 T4「适用场景」产出通用标签，不做生意适配评分。

### 远期版本任务（v0.3.0 ~ v1.0.0，进入该版本时拆解）

- v0.3.0：跨源比对引擎 + 共识统计 + 时效判定 + 冲突仲裁 + 领域上下文
- v0.4.0：去重指纹（Nigredo 配合）+ 长文切块 + 可解释钻取 UI + 评测集 + 偏见注记
- v0.5.0：新颖度/门槛维度 + 人肉覆盖 + 总览看板 + 成本计量 + 反馈学习回路
- v0.6.0：多模态/OCR 接入 + 伪造检测 + 引用核验 + 软广识别
- v1.0.0：Nigredo 网页/多适配器对接 + Rubedo SOP 闭环验证 + OpusMagnum 编排对接

---

## 五、设计基础（支撑主线落地）

### 5.1 数据契约（精炼知识对象）

```python
# core/models.py（MVP 字段，远期版本扩展不破坏兼容）
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
  ingestion_meta: {      # 预填熔知入库分面（ADR-005）：报告内嵌此块，入库即读取、无需重填
      content_type: str,        # 建议入库 content_type（15 类之一，如 tutorial/experience/sop/claim）
      domain: { udc_main: int,  # UDC 9 主类 0-9
                udc_code: str,  # 细分码（可选）
                label: str },
      temporal_nature: "evergreen"|"timeboxed"|"transient",  # 取代原 lifecycle 分面
      epistemic_status: "unverified"|"substantiated"|"corroborated",  # 由 quality.truthfulness.label 推
      trust_score: float,       # 0-1，同 quality 聚合
      knowledge_type: str,      # 知识类型（经验/方法/SOP/观点…）
      target_platform: str,     # 来源平台: bilibili/xiaohongshu/wechat/webpage…
      language: str,            # zh/en/…
      is_personal: bool,
      access_level: str,        # public/private/…
      lifecycle: str,           # 普通字段（已被 temporal_nature 取代分面地位）
      project_source: str       # 普通字段（已被 epistemic_status 取代分面地位）；建议填 "albedo-refined"
  }
```

**下游映射（交熔知时）**：以上字段全部预填进 `ingestion_meta`（ADR-005），熔知入库近乎「直读直存」——`quality.truthfulness.label` → `epistemic_status`（true→corroborated / suspect→unverified / false→rejected）；`trust_score` → 熔知 payload `trust_score`；`clean_text` 交熔知做切块 + 向量化 + 入库（分面分类已由 `ingestion_meta` 预填，熔知无需重做）。熔知 v1.5.0 待实施的「分面分类法重构（UDC 9 主类 / temporal_nature / epistemic_status）」与本法直接对齐，炼真产出的 `ingestion_meta` 即为其输入。

> 版本填充节奏：v0.1.0 仅填 `clean_text` / `quality.truthfulness` / `status` / `monetization.related`（**数据模型从一开始就设计成多维 + 以报告为主交付物**，避免 v0.2.0 推倒重来）；v0.1.0 最小报告由 T9 UI 直出；v0.2.0 补全 `quality.copywriting / structure / logic` + `merits` / `sop` / `provenance` / `trust_score` + `references` + `monetization` 全字段 + `report` 完整渲染。`business_line_tags` 已移除（业务线适配评分移出 Albedo）。

### 5.2 技术选型（MVP）

- **语言**：Python 3.13（对齐 Nigredo / Citrinitas 管理环境）
- **LLM**：DeepSeek，封装复用熔知 `_call_llm_api` 约定（env: `KB_LLM_BASE_URL` / `KB_LLM_MODEL` / `KB_LLM_API_KEY`）
- **UI**：Streamlit（与 Nigredo 一致，双击 run.bat 启动）
- **存储**：`data/out/<video_id>.json`（本地落盘，未来经 API 交熔知）
- **结构化输出**：LLM 输出严格 JSON（借鉴熔知 `_extract_json_block` 解析方式）
- **不引入**：向量库 / 复杂编排框架（MVP 单源顺序管线足够）

### 5.3 验收标准（MVP）

1. 丢一条各平台经验文字（字幕或结构化文案均可，当前以 B站 为主，或选 Nigredo 输出 JSON）→ 一键炼真 → 出一份**多维鉴定报告**（真实性评分 + 文案/结构/逻辑维度 + 核心优点 + 可照搬步骤 + 溯源）；报告醒目标注是否涉及变现、列出引用的书/网址；报告既能在界面看、也能导出 .md 直接给人读
2. 卖课谎言类内容能被标「可疑 / 虚假」并附理由
3. 产出 SOP 能被 Rubedo 直接读取消费（格式对齐）
4. 产出的鉴定报告（人直接读）内嵌「入库元数据」块，字段符合 5.1 契约；熔知入库时直接读取 `ingestion_meta` 预填分面，无需重填、无需重新分面（结构化 JSON 仅作 LLM 内部表示，不另交付）

### 5.4 竞品参考来源

- pangu-skill（盘古）：端到端人物/领域蒸馏，含质量验证审计
- nuwa-skill（女娲）：5 层认知提取 + 三重验证 + 保真度评分卡
- dalio-skill / skill-from-masters / colleague-skill / anyone-skill / immortal-skill / wisdom-council：人格/方法论蒸馏赛道
- OpenFactCheck：统一事实核查框架（Factcheck-GPT / RARR / Factool）
- TubeScribed：商业化「视频→标准 SOP」工具
- awesome-distill-skills / awesome-persona-skills：赛道精选列表（20+/54+ 项目）
- **（2026-07-09 补）多维/统计/信号/商业核查参照**：TruthfulnessEval / AIGVQA（多维质量）；Acrolinx / Writer / Grammarly / ETS e-rater（写作质量多维）；NumTemp / Cross-Document Fact Verification（统计验真）；Viblio（视频可信度信号，须加「互动≠证据」护栏）；Logically / FactBox.ai / iWeaver / Winston AI / FactSnap（商业单维事实核查器，仅作真实性一维参照）

> 详见 `docs/ALBEDO-RESEARCH-2026-07-09.md` 第十一节竞品全景分析。

---

## 六、研究课题与版本映射（已在计划中排期）

> **本区与主线（第三节）一一对应**：以下 22 项课题不是孤立清单，而是**已分配目标版本**的研究任务。进入对应版本时，再拆成具体任务（见第四节「远期版本任务」）。带 ★ 为优先项（成本最低、对一人公司最有用），在 v0.4.0 前即埋种子。
> 来源：2026-07-09 架构讨论「还有什么遗漏，头脑风暴一下」。用户指示：全部写入规划，之后再慢慢研究。

### 6.1 进料环节
| 课题 | 目标版本 | 说明 |
|---|---|---|
| ★ 去重 / 近重复检测 | **v0.4.0** | 同视频采两次、不同 UP 讲同一件事→先去重，避免重复炼、白花钱（需 Nigredo 配合指纹） |
| 超长内容切块 | **v0.4.0** | 2 小时课 vs 30 秒技巧长度差百倍，太长先切块再评，否则 LLM 丢上下文 |
| 采不到的内容标注 | **v0.4.0** | 微信付费文、B站会员专享适配器抓不到，标「采不到」而非假装没有（Nigredo 适配器职责，炼真消费标记） |
| 图里的信息丢了 | **v0.6.0** | PPT 对比图、视频演示画面只吃文字，图内数据/证据完全没进炼真（需上游 OCR/多模态） |

### 6.2 验真假本身的盲区
| 课题 | 目标版本 | 说明 |
|---|---|---|
| 域内外有别误伤 | **v0.3.0** | 酷家乐专属技巧在领域内真、放通用可能错；加领域上下文防误伤 |
| 全新说法无处印证 | **v0.3.0** | 刚出新方法网上无第二来源，跨源统计用不上，标「未印证」而非真假 |
| 伪造证据 | **v0.6.0** | AI 假截图、假数据图、深度伪造——统计只查文字数值，查不了图真假（远期多模态） |
| 评分主观偏见 | **v0.4.0** | 文案/结构/逻辑分是 LLM 审美，非客观真理——报告注明「这是风格分不是质量分」 |

### 6.3 提炼出的东西
| 课题 | 目标版本 | 说明 |
|---|---|---|
| 过时 SOP | **v0.3.0** | 2023 方法 2026 可能失效（与时效判定重叠），产出时顺手标时效风险 |
| 多冲突 SOP | **v0.3.0** | 不同来源步骤打架，提炼阶段提示「存在冲突版本」（与冲突仲裁重叠） |
| SOP 未验证 | **v1.0.0** | 产出标准步骤但没真跑过，与 Rubedo 闭环验证（真跑通验证） |

### 6.4 引用 / 变现的延伸
| 课题 | 目标版本 | 说明 |
|---|---|---|
| 引用未核实 | **v0.6.0** | 标了「推荐《XXX》书/某网址」但没验证真存在、真说过他声称的话（可能被断章取义当权威） |
| ★ 变现 ≠ 差内容护栏 | **v0.1.0 起步 / v0.5.0 深化** | 卖课不一定假、免费不一定真；变现标注不能和「可疑」画等号，报告分开呈现 |
| 软广识别 | **v0.6.0** | 比硬卖课难的「软广」（看似分享实则种草），卖课话术库主要抓硬广 |

### 6.5 用起来的闭环
| 课题 | 目标版本 | 说明 |
|---|---|---|
| 反馈回路 | **v0.5.0** | 你看完觉得「它判错了」，炼真记住纠正、下次更准（规模期学习回路） |
| 人肉覆盖 | **v0.5.0** | 你明知标「可疑」但觉得可用，一键「我信这个」并保留决定（UI） |
| 批量总览看板 | **v0.5.0** | 炼了 100 条后「哪些最值得做」汇总，而非 100 份报告散着 |
| 成本账 | **v0.5.0** | 每条调几次 LLM、花多少钱——一人公司要算账 |

### 6.6 怎么知道炼真自己靠谱
| 课题 | 目标版本 | 说明 |
|---|---|---|
| ★ 可解释到根因 | **v0.4.0** | 标「可疑」能点开看「因为第 X 条证据不足 / 数值前后矛盾」，否则不敢信（报告钻取） |
| ★ 评测集 | **v0.4.0** | 需一小批你亲自标过「真/假/好」的样本当考题，定期打分证明炼真判得对 |

### 6.7 战略层可加的评分维度
| 课题 | 目标版本 | 说明 |
|---|---|---|
| ★ 新颖度 | **v0.5.0** | 这条是老生常谈还是新打法？对你「新」往往更值钱（维度扩展） |
| ★ 上手门槛 / 前置成本 | **v0.5.0** | 做这事要多少工具/技能/钱？帮你判断「我现在能不能做」（维度扩展） |

> **排期原则**：★ 优先项在 v0.4.0 前即埋种子（报告注记 / 进料预处理 / 维度字段预留）；其余按上表归属版本。本区随路线演进，进入对应版本时拆为具体任务（见第四节）。

---

## 七、决策记录索引（ADR）

| ADR | 标题 | 一句话 | 文件 |
|---|---|---|---|
| ADR-002 | 范围扩张 | 多维鉴定 + 多源输入 + 平台信号归一化 + 文本类型感知 | `docs/ADR-002-SCOPE-EXPANSION.md` |
| ADR-003 | 产出形态 + 内容标注扩展 | 双输出 / 网页 / 变现 / 引用（**已被 ADR-004 部分取代**） | `docs/ADR-003-OUTPUT-FORM-AND-ANNOTATION.md` |
| ADR-004 | 取消双输出 | 以人能看的鉴定报告为主交付物，不另维护结构化 JSON 双输出 | `docs/ADR-004-DROP-DUAL-OUTPUT.md` |
| ADR-005 | 入库就绪 | 单一报告内嵌 `ingestion_meta`，预填熔知分面，入库直读直存 | `docs/ADR-005-INGESTION-READY-REPORT.md` |
