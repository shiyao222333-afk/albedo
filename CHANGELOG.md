# Changelog · 炼真 (Albedo)

本项目遵循 [Keep a Changelog](https://keepachangelog.com/) 约定，版本号采用语义化（MAJOR.MINOR.PATCH）。

## [Unreleased]（v0.2.0 切片 A 进行中）

### Added
- **A3 来源溯源** `core/provenance.py`：`build_provenance(inp) -> dict` 纯函数（不调 LLM），从 `AlbedoInput` 抽取 `video_id / up_name / source_url / title` + `processed_at`（**ISO 8601 UTC**，如 `2026-07-09T16:05:00Z`）；缺字段留空、绝不抛异常中断流水线；兼容 dict 输入（JSON 反序列化场景）。溯源种类扩展列入研究课题（§6.1，v0.4.0 起归本模块）。已通过 L1 语法 + L2 单测（18/18）。
- **A0 内容摘要基础层** `core/summary.py`：`summarize_content(clean_text, context="") -> dict`，产中性摘要 `summary{gist, bullets, key_claims}`——不评级、不判真假，与 merits/assess 严格分离，排净化后、评估前作压缩底座 + 报告开头。配套在 `core/models.py` 的 `RefinedKnowledgeObject` 补 `summary` 字段（§5.1 契约落地）。决策落地：gist 1~2 句 / bullets 3~7 / key_claims 2~5、语言跟原文、LLM 失败降级 gist=前 200 字、原文 <50 字跳过 LLM、超限截断。已通过 L1 语法 + L2 单测（6/6，覆盖空/短/正常/带context/LLM异常/超限）。
- **A1 优点分析编排** `core/merit.py`：`analyze_merits(clean_text, context="") -> dict`，五透镜萃取填 `merits` 8 子能力（内容轴 6：core_insight/reusable_steps/differentiation/pitfalls/applicable_scenarios/migration_cost + 形式轴 2：presentation_craft/format_reusable）。**2 次独立 LLM 调用**（内容轴 1 次 + 形式轴 1 次），形式轴挂了不影响内容轴；架构护栏——形式轴提示词明确"表达精彩不代表内容可信、不参与真实性判断"，且本模块绝不触碰 trust_score/status。降级：单轴失败对应字段留空、另一轴照常；语言跟原文、只提取不编造、信息不足该项留空；reusable_steps 为 high-level 可照搬步骤（与 A2 正式编号 SOP 层次不同）。已通过 L1 语法 + L2 单测（7/7，覆盖空/双轴正常/单轴失败/双轴失败/类型兜底/context注入）。
- **A2 结构化提炼编排** `core/structure.py`：`analyze_structure(clean_text, context="") -> dict`，先 `detect_structure_type()` 识别 8 类家族（sop/argument/case_study/comparison/narrative/qa/mixed/unknown），再路由提取——sop 型走 `extract_sop()`（TubeScribed 标准格式 `sop{purpose, preconditions, steps[idx,text], warnings, completion_checklist}`），其余型走通用大纲 `_generic_outline_extractor()`（`outline{overview, sections:[{subtitle, points}]}`，经 family 提示让大纲有意义）；**sop/outline 互斥填充**。**2 次 LLM 调用**（识别 + 路由提取）；非 sop 家族登记 `STRUCTURE_EXTRACTORS` 注册表（MVP 通用大纲复用，未来新题材插拔即扩，承载"多题材兼容"要求）。架构护栏——只提炼结构、不评级不判真假、不碰 trust_score/status；text_type 与 structure_type 正交。降级：识别失败→unknown→通用提取器；提取失败→留空 dict；识别值不在集合→纠偏 unknown。配套在 `core/models.py` 的 `RefinedKnowledgeObject` 补 `structure_type` / `outline` 字段（§5.1 契约落地，#708 中 summary 已由 A0 补）。已通过 L1 语法 + L2 单测（20/20，覆盖空/sop分支/非sop分支/unknown/识别抛异常/提取抛异常/类型纠偏/steps规整/字符串步骤列表）。
- **A4 鉴定报告渲染** `core/report.py`：`render_report(out, inp) -> str`，从精炼结果渲染人读 Markdown 报告（ADR-004 单报告，主交付物）。章节序（A4 决策）：结论卡 → A0 摘要 → 优点 8 子能力 → 结构化(SOP/大纲) → 溯源 → 数值预检；**输入通吃 dataclass / dict**（`out` 可传 `RefinedKnowledgeObject` 或其 `to_dict()`，`inp` 作溯源兜底）；**任何维度降级留空 → 显「（该维度未能生成）」不崩**；数值预检复用 `check_numeric_consistency(clean_text)`（纯规则、无 LLM、确定性——因 `assess.py` v0.2.0 冻结、数值结果不入契约，故报告段内重算）；红色信号英文标签映射中文（零基础高收益承诺 / 保本保过稳赚话术 / 极短时间见效承诺 / 暴富躺赚奇迹宣称）让报告说人话；sop/outline 互斥渲染。已通过 L1 语法 + L2 单测（8/8，覆盖全量 sop 分支 / 大纲分支互斥 / merits 降级 / summary 降级 / 空 out 不崩 / dataclass 输入 / 溯源回退 inp / 数值红信号中文映射）。
- **A5 编排补全** `flows/refine.py`：`refine()` 重写串联 v0.2.0 全链路——C2 净化 → #690 数值预检(hint 注入) → C3 真实性 `assess_truthfulness()`（失败时降级 suspect 不阻断）→ #691 变现 `assess_monetization()`（护栏仅标注）→ A0 `summarize_content()` → A1 `analyze_merits()` → A2 `analyze_structure()` → A3 `build_provenance()` → A4 `render_report()` 写入 `out.report`。**铁规矩：全程 try/except 包裹每步 LLM，失败→安全默认续跑，绝不整条中断；`assess.py` v0.2.0 一行不动（MVP 占位）**。组装完整 `RefinedKnowledgeObject`（含 report 字段，v0.2.0 主交付物）。已通过 L1 语法 + L2 单测（3/3，覆盖正常全链路 SOP 填充 / assess 失败降级 suspect / 全 LLM 失败不崩且报告含降级占位）。

## [0.1.0] - 2026-07-09（代码完成 + L4 用户验收通过）

> v0.1.0 目标：单条内容「能不能信」核心闭环——净化 + 真实性评估 + 变现标注 → 入库就绪报告。
> L4 验收：2026-07-09 真实端到端跑通（GPU large-v3 转写 BV1BXQABNE4y → 真实 DeepSeek 炼真出结果）。详见下方「验收记录」。

### Added
- **T1 数据契约** `core/models.py`：`AlbedoInput`（对齐 Nigredo `process()` 输出）+ `RefinedKnowledgeObject`（quality 从一开始就设计为多维对象 truthfulness/copywriting/structure/logic，v0.1.0 先填 truthfulness + status）。枚举：TextType / TruthfulnessLabel / EvidenceGrade / Status / MonetizationCategory。
- **T8 LLM 封装** `core/llm.py`：对齐熔知 `_call_llm_api`（DeepSeek，`KB_LLM_*` env，自动读 `.env`）；`extract_json_block` 花括号深度匹配容错；`call_llm_json` 组合并抛错。
- **T2 内容净化** `core/purify.py`：按 `text_type` 分支（字幕 ASR 清洗 / 结构化文案规整）+ 卖课话术特征模式库 `detect_sales_features()`（仅标注不删改，保留真实性证据）；多语言翻译占位。
- **T3 质量评估** `core/assess.py`：
  - 真实性评估 Prompt（nuwa 三重验证 + anyone-skill L1-L4 证据分级），`assess_truthfulness()` 调 LLM 填 `Truthfulness` 四维；
  - 数值自洽校验 `check_numeric_consistency()`（轻量规则，中文数字归一 + 过度承诺红色信号 + 同维度矛盾检测，结果注入真实性 Prompt 作补充证据）；
  - 变现检测 `assess_monetization()`（复用卖课特征，护栏「变现 ≠ 差内容」，related 仅标注不判假）。
  - `call_llm_json` 改为函数内惰性导入，使评估模块在缺 `requests` 环境也可导入（数值/变现检测不依赖 LLM）。
- **T7 流水线编排** `flows/refine.py`：`refine()` 串联 C2→C3，由 `quality.truthfulness.label` 推 `status`（true→accepted / suspect→suspect / false→rejected），组装最小 `RefinedKnowledgeObject`；`refine_text()` 便捷封装。
- **T9 最小 UI + 启动** `app.py` + `run.bat`：Streamlit 界面，粘贴文本 / 导入 Nigredo JSON → 一键炼真 → 展示净化文本 + 真实性 + 入库状态 + 变现标注，支持导出 `.md` 报告与 `.json` 对象；`run.bat` 自动装依赖并开 `http://localhost:8501`。

### 设计决策（详见 docs/ADR-005）
- 报告以「人能直接看」为主交付物：v0.1.0 由 T9 UI 直出最小报告，v0.2.0 再由 `core/report.py` 完整渲染。
- 变现标注与真实性结论解耦：卖课话术是真实性评估的**证据之一**，绝不仅凭「在卖课」判 false。
- 数据模型从 v0.1.0 起即设计为多维 + 入库就绪（`ingestion_meta` 预留），避免 v0.2.0 推倒重来。

### 验收记录（L4，2026-07-09）
- 真实端到端跑通：样例 `BV1BXQABNE4y`《我蒸馏了17个大佬给我打工（开源免费）》/ 花叔v
  - 馏析落盘：GPU faster-whisper **large-v3 + CUDA** 转写，440 段 / 5985 字 / 中文(概率 1.00)，落盘 `BV1BXQABNE4y.txt`（纯文本）+ `.srt`（带时间轴）
  - 炼真分析：真实 DeepSeek 跑 `refine()`，输出 `data/out/BV1BXQABNE4y_refined.json`
  - 鉴定结果：`label=suspect / score=45 / evidence_grade=L1 / status=suspect / monetization.related=false`
  - 结论解读：评估器仅看字幕文本、无法联网核实视频主张（如「4天6000+ star」），故严谨标「存疑」。这**正是 MVP 占位预期**——置信度/评估方式本就规划为 v0.3+ 大改。链路全通，验收通过。
- 配套改动（已 commit + 推送 Nigredo `cd1349e`）：馏析 `core/downloader.py` 新增字幕落盘（`.txt`+`.srt`），闭合「馏析→炼真」文件传递。

### 暂缓（非阻塞）
- **GitHub 推送**：已完成。2026-07-11 旧 `albedo` 仓库经本地备份 `D:\albedo-old` 后，以 v0.2.0 强制推送覆盖远程 `main`（自 commit `95ab329` 起）。旧代码（跨源矛盾检测引擎蓝图脚手架）分析见 `docs/ALBEDO-LEGACY-CODE-ANALYSIS.md`，其可复用模块（`ds_fusion.py` / `tms.py`）已纳入路线规划 §6.8 作为 v0.3.0 地基。
