# ADR-005: 入库就绪的报告（ingestion_meta 预填熔知分面）

## Status
Accepted

## Context

用户 2026-07-09 两句话把两条看似矛盾的要求拼到一起：
1. 之前（ADR-004）已决定**取消双输出**——炼真只对外交付一份人类可读鉴定报告（Markdown），不另维护"结构化 JSON + 报告"两套产物。
2. 现在又要求：**「最后的文档要方便熔知入库，熔知入库前要填写很多信息，炼真可以提前准备好。」**

也就是说：用户要"看得懂的报告"，但同时要这份报告"让熔知入库时几乎不用再填东西"。

背景事实——熔知（Citrinitas）入库需要的字段很多（来自其知识库 Schema v4.0 + 待实施的分面重构）：
- 分面：`content_type`(15 类) / `domain`(UDC 9 主类) / `temporal_nature`(evergreen|timeboxed|transient) / `epistemic_status`(unverified|substantiated|corroborated)
- Payload 索引字段：`trust_score` / `knowledge_type` / `target_platform` / `language` / `is_personal` / `access_level` / `lifecycle`(降级普通) / `project_source`(降级普通)

这些字段里，`epistemic_status` 和 `trust_score` 本来就是炼真质量评估的直接产物，`domain`/`temporal_nature`/`content_type`/`target_platform`/`language` 等也都能从炼真已掌握的信息（来源、文本类型、真实性结论、SOP 类型）合理推导。让熔知在入库时重做一遍分面分类，既重复劳动、又可能因上下文不足分错。

## Decision

**炼真交付单一人类可读鉴定报告（Markdown），但报告内嵌一个结构化「入库元数据」块（`ingestion_meta`），预填熔知入库所需的全部分面字段。** 熔知入库时直接读取 `ingestion_meta`，近乎"直读直存"，无需重填、无需重新分面。

具体：
- 对外唯一交付物 = 人类可读报告（Markdown）。结构化 JSON **仅作 LLM 内部表示**，不另交付、不维护（落实 ADR-004）。
- 报告内嵌 `ingestion_meta` 块（YAML front-matter 或定界代码块），字段见 PROJECT_PLAN 第五节数据契约：
  `content_type` / `domain{udc_main,udc_code,label}` / `temporal_nature` / `epistemic_status` / `trust_score` / `knowledge_type` / `target_platform` / `language` / `is_personal` / `access_level` / `lifecycle` / `project_source`。
- 映射关系：
  - `epistemic_status` ← `quality.truthfulness.label`（true→corroborated / suspect→unverified / false→rejected）
  - `trust_score` ← 质量聚合分（0-1）
  - `domain.udc_main` ← 由内容主题推导 UDC 9 主类（对齐熔知 v1.5.0 分面重构）
  - `temporal_nature` ← 由时效判定推导（evergreen/timeboxed/transient）
  - `target_platform` ← 来源平台（bilibili/xiaohongshu/wechat/webpage…）
  - `content_type` ← 由文本类型+产出类型推导（tutorial/experience/sop/claim…）
- 新增任务 **T14** `core/ingest_meta.py` 负责推导与写入（归属 v0.2.0，与完整报告同期；v0.1.0 起先预埋 `epistemic_status`+`trust_score` 两个最稳的字段）。

## Consequences

**变得更容易：**
- 熔知入库从"重新分面 + 填字段"降为"读 `ingestion_meta` 直存"，省一道工序、少一处分面不一致风险。
- 炼真与熔知的分面口径在**设计期就对齐**（UDC 9 主类 / temporal_nature / epistemic_status 三者直接对应熔知 v1.5.0 重构），将来五器合体无需返工。
- 保持 ADR-004 的"单报告"简单性——没有引入第二份维护产物。

**变得更难 / 需留意：**
- 炼真要"懂"熔知的分面体系（UDC 分类、字段取值），等于承担了一部分原本纯属熔知的分面职责——但只到"预填建议"层级，熔知仍保留最终裁决权（可覆盖 `ingestion_meta`）。
- `domain`(UDC) 推导需要主题分类能力，MVP 用 LLM 启发式即可，规模期再校准。
- 报告里嵌结构化块会增加报告渲染复杂度（T12 报告渲染需同时产出人读正文 + 元数据块）。

## 影响的文档
- `BLUEPRINT.md`：§二 #6 改为"入库就绪的报告"；§五 准则 #6 已为单报告交付（ADR-004），本次补"内嵌入库元数据"语义。
- `FLOWCHART.md`：C7 输出加 `ingestion_meta`；接口边界"Albedo 交付物"段改写为单一报告 + 内嵌入库元数据（ADR-004/005）。
- `PROJECT_PLAN.md`：§二 #6 改"入库就绪的报告"；§四 任务加 T14；§五 数据契约加 `ingestion_meta` 块、下游映射改写为"经 ingestion_meta 预填"；§七 验收 #4 改为单一报告 + 内嵌入库元数据；新增 §九 遗漏清单、Backlog 段。
- 新建本 ADR-005。

## 与 ADR-004 的关系
ADR-004 取消"双输出（JSON + 报告）"，确立单一人类可读报告为主交付物。ADR-005 在 ADR-004 基础上进一步明确：**这份单一报告内嵌 `ingestion_meta`，让它天然入库就绪**。两者不冲突——没有新增第二份产物，只是让唯一产物携带机器可读的元数据块。
