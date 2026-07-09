# 炼真（Albedo）项目计划

> 当前版本：**v0.1.0（MVP：验真假核心闭环）**
> 蓝图：见 `BLUEPRINT.md` ｜ 调研报告：见 `docs/ALBEDO-RESEARCH-2026-07-09.md`
> 最后更新：2026-07-09

---

## 一、竞品借鉴地图（MVP 每个能力从哪来）

我们不做重复造轮子——能借鉴的成熟方法直接拿来，只在「独特之处」下功夫。

| 我们的能力（MVP） | 借鉴自竞品 / 研究 | 我们的独特处理 |
|---|---|---|
| **质量评估**（真/假/可疑 + 0-100 分 + 理由） | **nuwa-skill** 三重验证 + **anyone-skill** L1-L4 证据分级 + **OpenFactCheck** 统一核查管线 | 单源 LLM 实现；**为规模期跨源比对预留接口**；输出直接映射熔知 `epistemic_status` |
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

2. **平台无关的认知精炼**
   竞品多绑死单一采集源（如某站视频）。Albedo 只吃「文字」——Nigredo 产出的生料文本，不绑任何平台（B站 / YouTube / 公众号 / 小红书 等皆可）。未来任何来源的文字都能炼，天然适配你多业务线、多采集源的格局。

3. **多 SOP 并列产出，对接 Rubedo**
   竞品产出「可安装 Skill」；Albedo 产出「**可被执行的标准 SOP**」，直接进凝华（Rubedo）的 SOP 建立环节——贴合你「多个 SOP 并列进行」的工作方式。

4. **跨源矛盾检测（规模期独门空间）**
   单人蒸馏无矛盾可检，单条事实核查不跨源比经验。Albedo 未来做「多教程互相印证 / 冲突仲裁」——竞品的空白区。

5. **FPF 信任聚合（熔知移交）**
   从熔知移交的核心能力，竞品无对应物。

---

## 三、版本路线

| 版本 | 目标 | 关键能力 |
|---|---|---|
| **v0.1.0（当前）** | MVP 验真假核心闭环 | 内容净化（去广告/轻量纠错）+ 质量评估（真/假/可疑 + 理由）；先跑通单条最小可用 |
| v0.2.0 | 完整鉴定报告 + 批量 | 优点分析（6 子能力）+ 结构化 SOP + 溯源 + 批量/队列并行处理 |
| v0.3.0 | 验真假深化（规模期） | 跨源矛盾检测 + 时效判定 + 冲突仲裁（基础验真假已稳，规模期一次做实） |

> 注：原「v0.3.0 业务线适配评估」已移出 Albedo——4 条业务线适配度评分归凝华（Rubedo）SOP 建立 / 总指挥部（OpusMagnum）编排；Albedo 只产出通用 SOP 与适用场景标签，不做生意适配评分。

---

## 四、任务清单（按版本分组）

> 原则：每个任务对应 FLOWCHART 节点；MVP 只做单源闭环；竞品已有成熟方法的用 LLM 启发式快速实现，不为 MVP 自建复杂管线。

### v0.1.0 验真假核心闭环 [MVP必须]

- **T1** 数据契约 `core/models.py`：定义 `AlbedoInput`（对齐 Nigredo `process()` 输出：text / video_id / title / up_name / source_url）+ `RefinedKnowledgeObject`（全字段，v0.1.0 先填 clean_text / quality / status）📍C1/C7
- **T2** 内容净化 `core/purify.py`：去广告话术（卖课特征模式库）、轻量 ASR 纠错、多语言翻译占位 📍C2
- **T3** 质量评估 `core/assess.py`：LLM 单源评估 → `label(真/假/可疑)` + `reasoning`；借鉴 nuwa 三重验证思路 + anyone-skill 证据分级 📍C3
- **T7** 流水线编排（最小）`flows/refine.py`：串联 C2→C3，组装最小 `RefinedKnowledgeObject`，由 quality.label 推 status 📍C1→C7
- **T8** LLM 调用封装 `core/llm.py`：对齐熔知 `_call_llm_api`（DeepSeek，env 配置 base_url/api_key/model），供 C3 复用 📍C3
- **T9** 最小 UI `app.py` + `run.bat`：粘贴文本（或选 Nigredo 输出 JSON）→ 一键炼真 → 展示「真假鉴定」📍C7

### v0.2.0 完整鉴定报告 + 批量 [MVP延伸]

- **T4** 优点分析 `core/merit.py`：LLM 结构化输出 6 子能力（核心洞察 / 可复用步骤 / 差异化亮点 / 适用场景 / 陷阱预警 / 迁移成本）；借鉴 skill-from-masters + nuwa 诚实边界 📍C4
- **T5** 结构化提炼 `core/structure.py`：产出标准 SOP（目的 + 前置条件 + 编号步骤 + 警告 + 完成清单），对齐 TubeScribed 格式 📍C5
- **T6** 溯源 `core/provenance.py`：从 Nigredo `info` 取 video_id / up_name / source_url / title + 记录 processed_at 📍C6
- **T7+** 流水线补全 `flows/refine.py`：扩展编排串入 C4→C6，补全 `RefinedKnowledgeObject` 全字段（merits / sop / provenance）+ FPF 轻量 trust_score 📍C1→C7
- **T11** 批量 / 队列（方案A）：参考 Nigredo 队列机制，支持多条生料并行炼真 📍C1

### 已移出 Albedo（归其它项目）

- ~~业务线适配度评分（原 T10）~~：归凝华 Rubedo SOP 建立 / 总指挥部 OpusMagnum 编排；Albedo 仅在 T4「适用场景」产出通用标签，不做生意适配评分。

---

## 五、数据契约（精炼知识对象）

```python
# core/models.py（MVP 字段，规模期扩展不破坏兼容）
AlbedoInput:
  text: str            # 净化前生料（Nigredo subtitle.full_text）
  video_id: str = ""   # Nigredo info.bvid
  title: str = ""      # Nigredo info.title
  up_name: str = ""    # Nigredo info.owner.name
  source_url: str = ""

RefinedKnowledgeObject:
  input_ref: AlbedoInput
  clean_text: str                          # C2 净化后
  quality: { label: "true"|"false"|"suspect",
             score: 0-100,
             reasoning: str,
             evidence_grade: "L1"|"L2"|"L3"|"L4" }   # C3
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
  status: "accepted"|"suspect"|"rejected"  # 由 quality.label 推
```

**下游映射（交熔知时）**：`quality.label` → `epistemic_status`（true→corroborated / suspect→unverified / false→rejected）；`trust_score` → 熔知 payload `trust_score`；`clean_text` 交熔知做分面分类 + 切块 + 向量化 + 入库。

> 版本填充节奏：v0.1.0 仅填 `clean_text` / `quality` / `status`；v0.2.0 补全 `merits` / `sop` / `provenance` / `trust_score`。`business_line_tags` 已移除（业务线适配评分移出 Albedo）。

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

1. 贴一条各平台经验文字（当前以 B站 为主，或选 Nigredo 输出 JSON）→ 一键炼真 → 出一份说人话的「鉴定报告」（可信度 + 优点 + 可照搬步骤 + 溯源）
2. 卖课谎言类内容能被标「可疑 / 虚假」并附理由
3. 产出 SOP 能被 Rubedo 直接读取消费（格式对齐）
4. 报告落 `data/out/*.json`，字段符合第五节契约

---

## 八、竞品参考来源

- pangu-skill（盘古）：端到端人物/领域蒸馏，含质量验证审计
- nuwa-skill（女娲）：5 层认知提取 + 三重验证 + 保真度评分卡
- dalio-skill / skill-from-masters / colleague-skill / anyone-skill / immortal-skill / wisdom-council：人格/方法论蒸馏赛道
- OpenFactCheck：统一事实核查框架（Factcheck-GPT / RARR / Factool）
- TubeScribed：商业化「视频→标准 SOP」工具
- awesome-distill-skills / awesome-persona-skills：赛道精选列表（20+/54+ 项目）

> 详见 `docs/ALBEDO-RESEARCH-2026-07-09.md` 第十一节竞品全景分析。
