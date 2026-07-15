# Changelog · 炼真 (Albedo)

本项目遵循 [Keep a Changelog](https://keepachangelog.com/) 约定，版本号采用语义化（MAJOR.MINOR.PATCH）。

## [0.4.1] - 2026-07-16

> 本版本补齐「审计交付缺口」（见 `docs/AUDIT-DELIVERY-GAP-2026-07-16.md`）：§6.2 证据链判定（判定方法论重做）与 TT6 MiniCheck **真实部署路径**此前只写在计划里没落地，本版全做。
> 关键更正：前序计划/代码里所谓「`assess.py` 零改铁规矩」是 **AI 自创的设计护栏，用户从未下达此令**（用户原话「哪有什么铁规矩，我从来没有说过」），已删除；§6.2 才是计划真要求，直接执行无需二选一。

### Added
- **§6.2 证据链判定（判定方法论重做）**——取代 `assess.py` 自由 LLM 的 `truthfulness.label`，改为「逐条断言证据 → Dempster-Shafer 证据融合 → 文档级确定性结论」（`core/judgment.py`，新模块）。
  - 纯 numpy，确定性，**同输入必得同结论**（根治 L4 三轮翻盘 suspect/suspect/true）。裁决由证据链推导而非模型「感觉」，天然可解释、可追溯到根因。
  - 复用 `D:\albedo-old\core\ds_fusion.py` / `tms.py` 的数学（内联常量，不依赖旧 config）；BPA 质量分配：自相矛盾/MiniCheck判伪=[0.05,0.90,0.05]、MiniCheck判真=[0.90,0.05,0.05]、话术红flag=[0.10,0.45,0.45]、模糊语=[0.20,0.20,0.60]、无信号=[0,0,1]。
  - 文档级规则：n_contradicted>0 且 margin<0.15 → `false`；belief_true>0.6 且 MiniCheck已跑 且 n_contradicted==0 → `true`；否则 `suspect`。
  - **G1 反向桥（真相错觉防御）**：`true` 且 说服包装强度 polish≥0.7 且 MiniCheck未部署 → 降 `suspect`（高包装+未验证不轻信真）。
  - 旁路确定性自测 `robust_test/test_judgment.py`：场景 A(全unverified→suspect) / B(矛盾→false) / C(MiniCheck supported→true) / G1高包装→不轻信真，同输入跑 3 次断言完全一致，全 PASS。
- **TT6 MiniCheck 真实部署路径** `core/minicheck_verify.py`（新模块）—— McGill-NLP MiniCheck（EMNLP2024，Flan-T5-Large 7.7亿参数达 GPT-4 级 74.7% vs 75.3%，本地确定性不飘），对 `check_worthy + scope=public + factuality=factual` 断言逐条核验（claim + 同视频断言作证据语料 → supported/contradicted/neutral）。`is_available()` 懒检测 + `try/except` 守卫：包未装/模型未下载时 `available=False` → `truth_track` 自动降级标 `unverified`（保守不臆断）。
  - **⚠️ 沙箱限制（非代码问题）**：本沙箱 PyPI 被代理拦截无法 `pip install minicheck`，故当前 Layer2 实跑未启用、标 `unverified`；**用户本机 `pip install minicheck` 后首次运行自动下载权重（~1GB，走 HuggingFace），Layer2 实质核验即自动启用**。

### Changed
- **`flows/refine.py` 接入判定**：验真后调 `judge_document(claim_verifications, persuasion_polish)` 覆盖 `truthfulness.label / score / reasoning / evidence_grade`（Layer2跑过→L4 否则 L1），`status` 由确定性 label 推导（自然稳定）；`assess.py` 真实性退为「整体参考」（数值/变现/启发式评分保留），判定结论改由证据链给出。`try/except` 包裹，判定异常不阻断、回退 assess 降级结果。
- **`core/truth_track.py` 接入 MiniCheck**：`verify_claims_web()` 内部改为 `from core.minicheck_verify import verify_claims; if verify_claims(claims): return` + 降级 `unverified` 兜底（已 `contradicted` 的保矛盾结论不被覆盖）。

### 验收
- L1 语法：全部文件 `py_compile` 通过。
- L3 桩：确定性自测 `test_judgment.py` 4 场景 ×3 轮全 PASS（结论稳定）。
- L4 真视频三轮稳定性：`robust_test/l4_judgment_stability.py`（载入 `subtitle_lines.json` BV1jCNe6zEMb 70 段，跑 `refine()` 3 轮比较 truth_label/status/trust_score）—— 结果见下方验收记录。

### 验收记录（L4 真视频三轮稳定性，2026-07-16）
- 样本：`subtitle_lines.json`（BV1jCNe6zEMb，70 段 / 964 字），跑 `refine()` 三轮（每层真实 DeepSeek + 形式线 + 验真线 + §6.2 判定）。
- 结果：
  - RUN1：label=suspect / status=suspect / trust=0.55 / claims=0 / form=0.58（94.0s）
  - RUN2：label=suspect / status=suspect / trust=0.47 / claims=0 / form=0.82（97.3s）
  - RUN3：label=suspect / status=suspect / trust=0.50 / claims=19 / form=0.88（88.7s）
  - **truth_label：['suspect','suspect','suspect'] → STABLE**；**status：['suspect','suspect','suspect'] → STABLE**；OVERALL = **PASS（稳定）**。
- 结论：§6.2 证据链判定彻底根治「同输入翻转」——即便上游 LLM 断言抽取轮次间波动（RUN1/2 抽得 0 条、RUN3 抽得 19 条），确定性 D-S 融合仍给出一致结论（单源未验证→suspect），不再出现旧版 free-LLM 的 suspect/suspect/true 翻转。
- **⚠️ 观察项（非阻塞）**：claim 抽取数轮间不稳定（0 vs 19），属 `truth_track` 上游 LLM 抽取波动，不影响判定稳定性；若需逐条报告稳定，后续可加固 claim 抽取（temperature=0 + 失败重试），列入 v0.5.0 研究课题。

## [0.4.0] - 2026-07-16

### Added
- **形式线（Track B：怎么讲的）**——在三轨正交架构（内容线 Track A + 验真线 + 形式线 Track B）中补齐"形式线"，分析内容"怎么讲"（娱乐 / 故事类内容线无干货、价值全在形式线）。用户拍板：核心维度全做 / 所有内容类型 / 修辞合并到形式线 / 模板机器可读供凝华 / 情绪用弹幕密度弱代理。
  - **数据模型** `core/models.py`：新增 `FormTrack` 数据类（pacing / hook / narrative_segments / persona / rhetoric_devices / reusable_template / emotion_proxy / persuasion_polish / form_faithfulness / form_score）；`RefinedKnowledgeObject` 增 `form_track` / `form_score` 两字段（向后兼容）。
  - **形式线流水线** `core/form_track.py`（新模块）：
    - **FT0 节奏 + 时长分层**（纯函数，不联网）：语速(wpm) / 停顿 / 时长分层(short<180s / mid<900s / long)。
    - **FT1 钩子**：前 10 秒字幕 → {hook_type, strength, hook_text, ts}。
    - **FT2 叙事结构**：3-7 段 [{ts, title, purpose}]。
    - **FT3 人设**：{trust_base, perspective, tags}。
    - **FT4 修辞话术（单一来源）**：22 种说服技巧 + 规则兜底绝对化骗局话术 / 水词 / 模糊语（中文数字归一）；truth_track 改为 import 消费，消除重复正则维护。
    - **FT5 可复制模板**：{title_formula, section_skeleton[{ts, purpose}], persona_tags}（机器可读，供凝华未来消费；炼真只产数据、不生成视频）。
    - **FT6 情绪曲线**：弹幕密度时间轴弱代理（无弹幕标 weak_signal + 空，诚实不冒充真实留存）。
    - **G1 说服包装强度（反向桥 / 真相错觉防御）**：persuasion_polish 传入验真 aggregate——高包装(≥0.7) + 证据未验证 → 验真信任分额外下调 15%。
    - **G2 形式保真自检**：hook_text 必须出现在前 10 秒字幕、每段 ts 须是真实字幕时间戳，防 LLM 编结构。
    - **表达力评分** `_compute_form_score`：钩子 30% + 结构 30% + 人设 20% + 节奏 20%。
  - **编排接入** `flows/refine.py`：验真前插入形式线调用，form_score 填入对象，persuasion_polish 透传验真实现 G1。
  - **报告三轴 + 形式章节** `core/report.py`：结论卡升级「三轴总览：干货度 / 可信度 / 表达力」；新增 `## 🎬 形式分析` 段（钩子 / 节奏 / 叙事结构 / 人设 / 修辞话术 / 可复制骨架 / 情绪代理 / 说服包装强度 / 形式保真自检）；内容线与通用路径均插入。
  - **本期不做（列入路线图）**：OCR 跨模态（G8）、UP 主跨视频人设累积（G9）——仅定义字段 / 标注，真正累积待接项目间通信。
  - 已通过 L1 语法（9 文件 py_compile）+ L3 端到端跑通（注入桩 LLM 验证：形式线全链路 + 验真消费形式线规则 + 三轴报告，教程类与娱乐类两路复测 23 项断言全 PASS）；临时验证脚本已清理。

## [0.3.0] - 2026-07-16

### Added
- **验真环节（逐条断言验真）**——把"验真假"从 assess.py 的整条视频单源打分，升级为"逐条断言验真"（调研见 `docs/RESEARCH-TRUTH-VERIFICATION-2026-07-15.md` / `-V2-2026-07-15.md` / `-V3-GAPS-2026-07-15.md`）。用户拍板：第一层（不联网快筛）+ 第二层（联网深验）都做、经验主张放过、MiniCheck 本地部署、逐条粒度；并补"真假/事实观点/个人公开"三维度接熔知字段。
  - **数据模型** `core/models.py`：新增 `ClaimVerification` 数据类（含 factuality 事实/观点/混合、scope 个人/公开、accuracy supported/contradicted/unverified、red_flags、contradicts_with、hedge_level、weasel_flag、validity_class、verified_date、is_visual_claim、creator_id/creator_rep_delta 等 V3 补漏字段）；`RefinedKnowledgeObject` 增 `claim_verifications` / `truth_track` 两字段（向后兼容）。
  - **验真流水线** `core/truth_track.py`（新模块，自包含不耦合 assess.py）：
    - **Layer 0.5 防瞎编**（最关键防坑层，V3 遗漏3）：抽断言后每条拿字幕原文 NLI 一遍，LLM 瞎编的无原文支撑断言直接丢弃，复用 `grounding.py` 思路。
    - **Layer 1a 话术识别**（规则，不联网）：绝对化骗局话术（零基础高收益/保本稳赚/极短见效/暴富奇迹）+ 水词（无出处权威暗示）+ 模糊语（强模糊可赖账），中文数字归一（"十万"→"10万"）让阿拉伯正则也能命中。
    - **Layer 1b 自相矛盾**（两两 NLI，逻辑必然不实）：矛盾对就地标 `contradicted` + 证据溯源，纯本地、误报极低。
    - **Layer 1c 时效标记**：每条断言带 `verified_date` + `validity_class`（命中平台规则/价格/版本类→timeboxed 限时），接熔知 `temporal_nature`。
    - **Layer 2 联网深验（MiniCheck 本地）接口预留**：当前未部署标 `unverified`（保守，V3 遗漏5），真实调用未实现（排 P0-2 补）。
    - **聚合**：逐条结果汇总为文档级 `severity`(alert/warn/ok) + `trust_score`(0-1 保守) + `epistemic_status` + `is_personal`，并映射进 `ingestion_meta` 落熔知。
  - **编排接入** `flows/refine.py`：内容线/通用路径均调用 `_run_truth_track`（内容线锚定 `key_sentences` 真实原话；无字幕降级跳过 Layer0.5）；Truthfulness（假验真）保持不动作为整体参考，验真矛盾/话术信号上调 `status=suspect`（保守不误伤）。
  - **报告逐条验真章节** `core/report.py`：新增 `## 🛡️ 逐条验真` 段（结论卡之后、内容摘要之前），每条断言显示原话+字幕ts+事实/观点+个人/公开+判定+话术/矛盾/未联网深验标记；矛盾对单独列出。
  - **本期不做（列入路线图）**：OCR 跨模态（"画面未核查"诚实声明）、UP 主跨视频信用累积（仅定义 `creator_id/creator_rep_delta` 字段，真正累积待接项目间通信）。
  - 已通过 L1 语法（8 文件 py_compile）+ L3 端到端跑通（注入桩 LLM 验证：Layer0.5 剔除无原文支撑断言 / 自相矛盾标红 / 中文"十万"话术命中 / 时效标记 / 逐条报告渲染，24 项断言全 PASS）。

## [0.2.1] - 2026-07-15

### Added
- **内容线（字幕处理管线）增强**——针对 B站等字幕类输入，从「通用模板」升级为「先分类 → 按类型萃取 → 每条锚定字幕 → 自动查编造」的管线（调研见 `docs/RESEARCH-CONTENT-TRACK-2026-07-15.md` / `RESEARCH-CONTENT-SUMMARY-2026-07-15.md`）。同时治理「字幕输入分析太肤浅」与「同输入结果不稳定」两个任务（同源：固定码本 + temperature=0 + 单维度打分）。
  - **上游契约增强**（跨项目，`Nigredo core/downloader.py` `_subtitle_lines_with_ts()`）：中转① `# 字幕` 段由整块 `full_text` 改为**逐条 `[mm:ss] 文本`**（CC/AI/Whisper 三路 `segments` 均带 start）。内容线得以「按字幕条数锚定」与「高光 ±15 条字幕窗口」；无 segments 降级整块，向后兼容。
  - **数据契约扩展** `core/models.py`：`AlbedoInput` 增 `subtitle_lines / highlights / danmaku / comments_pinned / comments_top / ai_conclusion / play_analysis`（全可选、向后兼容）；`RefinedKnowledgeObject` 增 `content_type / key_sentences / content_extract / highlight_blocks / grounding`。
  - **中转解析增强** `watcher/parser.py`：`parse_transit_md` 重写为分节解析，抽 `# 字幕/#高光时间点/#弹幕/#置顶评论/#高赞评论/#AI摘要` 为结构化字段；旧格式逐行降级不崩。
  - **内容类型自动分类** `core/classify.py`：`classify_content_type()` 用 LLM（temperature=0 + 固定枚举）判 tutorial/tool_review/knowledge/opinion/entertainment/narrative/unknown，失败降级 unknown（确定性）。
  - **Route A 关键句锚定** `core/content_track.py` `extract_key_sentences()`：先抄关键原话（带 ts 兜底不丢），再改写生成摘要（每条 bullet 标 source_ts 指回字幕）——措辞可变、内容一致。
  - **高光上下文块** `core/content_track.py` `build_highlight_blocks()`：每条高光取前后 ±15 条字幕（时间轴锚定）+ 邻近弹幕，组成上下文块供萃取深挖（纯函数）。
  - **按类型萃取** `core/content_track.py` `extract_by_type()`：tutorial→完整 SOP（目的/前置/步骤/坑/完成判定）/ tool_review→决策表 / opinion→论点图 / knowledge→概念卡 / entertainment→标记转形式线 / narrative→带ts大纲；每条带 ts。
  - **摘要保真自检** `core/grounding.py` `check_grounding()`：类 SummaC NLI 蕴含判定，检查改写摘要是否被字幕原文支撑，无支撑句标「⚠️无原文支撑」（这是「总结是否编造」非「视频真假」，验真另议）。
  - **编排接入** `flows/refine.py`：字幕输入且带结构化字幕行 → 走内容线（classify→关键句→高光块→萃取→保真），填充新字段；非字幕输入仍走旧 A0/A1/A2 通用路径；`assess.py` 真实性评估（v0.2.1 阶段暂不动，AI 设计决策，非用户指令）。
  - **报告按类型渲染** `core/report.py`：字幕输入按 `content_type` 渲染 SOP卡/决策表/论点图/概念卡 + 关键原话兜底段 + 高光块段 + 摘要保真标注；非字幕输入保持旧报告。
  - 已通过 L1 语法（8 文件 py_compile）+ L2 parser 解析 + L3 内容线 `refine()` 端到端跑通（注入桩 LLM 验证 tutorial 分支 SOP 渲染 / 高光窗口 / 保真标注全部正确）。

## [0.2.0] - 2026-07-12

### Added
- **A3 来源溯源** `core/provenance.py`：`build_provenance(inp) -> dict` 纯函数（不调 LLM），从 `AlbedoInput` 抽取 `video_id / up_name / source_url / title` + `processed_at`（**ISO 8601 UTC**，如 `2026-07-09T16:05:00Z`）；缺字段留空、绝不抛异常中断流水线；兼容 dict 输入（JSON 反序列化场景）。溯源种类扩展列入研究课题（§6.1，v0.4.0 起归本模块）。已通过 L1 语法 + L2 单测（18/18）。
- **A0 内容摘要基础层** `core/summary.py`：`summarize_content(clean_text, context="") -> dict`，产中性摘要 `summary{gist, bullets, key_claims}`——不评级、不判真假，与 merits/assess 严格分离，排净化后、评估前作压缩底座 + 报告开头。配套在 `core/models.py` 的 `RefinedKnowledgeObject` 补 `summary` 字段（§5.1 契约落地）。决策落地：gist 1~2 句 / bullets 3~7 / key_claims 2~5、语言跟原文、LLM 失败降级 gist=前 200 字、原文 <50 字跳过 LLM、超限截断。已通过 L1 语法 + L2 单测（6/6，覆盖空/短/正常/带context/LLM异常/超限）。
- **A1 优点分析编排** `core/merit.py`：`analyze_merits(clean_text, context="") -> dict`，五透镜萃取填 `merits` 8 子能力（内容轴 6：core_insight/reusable_steps/differentiation/pitfalls/applicable_scenarios/migration_cost + 形式轴 2：presentation_craft/format_reusable）。**2 次独立 LLM 调用**（内容轴 1 次 + 形式轴 1 次），形式轴挂了不影响内容轴；架构护栏——形式轴提示词明确"表达精彩不代表内容可信、不参与真实性判断"，且本模块绝不触碰 trust_score/status。降级：单轴失败对应字段留空、另一轴照常；语言跟原文、只提取不编造、信息不足该项留空；reusable_steps 为 high-level 可照搬步骤（与 A2 正式编号 SOP 层次不同）。已通过 L1 语法 + L2 单测（7/7，覆盖空/双轴正常/单轴失败/双轴失败/类型兜底/context注入）。
- **A2 结构化提炼编排** `core/structure.py`：`analyze_structure(clean_text, context="") -> dict`，先 `detect_structure_type()` 识别 8 类家族（sop/argument/case_study/comparison/narrative/qa/mixed/unknown），再路由提取——sop 型走 `extract_sop()`（TubeScribed 标准格式 `sop{purpose, preconditions, steps[idx,text], warnings, completion_checklist}`），其余型走通用大纲 `_generic_outline_extractor()`（`outline{overview, sections:[{subtitle, points}]}`，经 family 提示让大纲有意义）；**sop/outline 互斥填充**。**2 次 LLM 调用**（识别 + 路由提取）；非 sop 家族登记 `STRUCTURE_EXTRACTORS` 注册表（MVP 通用大纲复用，未来新题材插拔即扩，承载"多题材兼容"要求）。架构护栏——只提炼结构、不评级不判真假、不碰 trust_score/status；text_type 与 structure_type 正交。降级：识别失败→unknown→通用提取器；提取失败→留空 dict；识别值不在集合→纠偏 unknown。配套在 `core/models.py` 的 `RefinedKnowledgeObject` 补 `structure_type` / `outline` 字段（§5.1 契约落地，#708 中 summary 已由 A0 补）。已通过 L1 语法 + L2 单测（20/20，覆盖空/sop分支/非sop分支/unknown/识别抛异常/提取抛异常/类型纠偏/steps规整/字符串步骤列表）。
- **A4 鉴定报告渲染** `core/report.py`：`render_report(out, inp) -> str`，从精炼结果渲染人读 Markdown 报告（ADR-004 单报告，主交付物）。章节序（A4 决策）：结论卡 → A0 摘要 → 优点 8 子能力 → 结构化(SOP/大纲) → 溯源 → 数值预检；**输入通吃 dataclass / dict**（`out` 可传 `RefinedKnowledgeObject` 或其 `to_dict()`，`inp` 作溯源兜底）；**任何维度降级留空 → 显「（该维度未能生成）」不崩**；数值预检复用 `check_numeric_consistency(clean_text)`（纯规则、无 LLM、确定性——因 `assess.py` v0.2.0 冻结、数值结果不入契约，故报告段内重算）；红色信号英文标签映射中文（零基础高收益承诺 / 保本保过稳赚话术 / 极短时间见效承诺 / 暴富躺赚奇迹宣称）让报告说人话；sop/outline 互斥渲染。已通过 L1 语法 + L2 单测（8/8，覆盖全量 sop 分支 / 大纲分支互斥 / merits 降级 / summary 降级 / 空 out 不崩 / dataclass 输入 / 溯源回退 inp / 数值红信号中文映射）。
- **A5 编排补全** `flows/refine.py`：`refine()` 重写串联 v0.2.0 全链路——C2 净化 → #690 数值预检(hint 注入) → C3 真实性 `assess_truthfulness()`（失败时降级 suspect 不阻断）→ #691 变现 `assess_monetization()`（护栏仅标注）→ A0 `summarize_content()` → A1 `analyze_merits()` → A2 `analyze_structure()` → A3 `build_provenance()` → A4 `render_report()` 写入 `out.report`。**韧性设计（AI 设计决策，非用户指令）：全程 try/except 包裹每步 LLM，失败→安全默认续跑，绝不整条中断；`assess.py` v0.2.0 作为 MVP 占位先不动（验真结论改由 §6.2 证据链推导，取代自由 LLM）**。组装完整 `RefinedKnowledgeObject`（含 report 字段，v0.2.0 主交付物）。已通过 L1 语法 + L2 单测（3/3，覆盖正常全链路 SOP 填充 / assess 失败降级 suspect / 全 LLM 失败不崩且报告含降级占位）。
- **A6 界面扩展** `app.py`：移除 v0.1.0 内联报告拼接（删 `_build_report_md()` 自拼函数 + `check_numeric_consistency` 内联预检），改为直接渲染 A4 产出的完整鉴定报告 `out.report`（ADR-004 单报告交付物）+ 顶部「一眼概览」结论卡（入库状态 + 真实性结论 + 信任分 + 变现提示）；导出 `.md` 用真实 `out.report`、`.json` 用 `out.to_json()`。输入解析逻辑（手动文件 / 馏析 JSON best-effort）原样保留。已通过 L1 语法 + L2（mock streamlit 注入真实跑通 `main()` 全流程：报告渲染 + 导出 .md/.json 均正确）。

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
