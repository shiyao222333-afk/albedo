# 炼真（Albedo）数据流程框图

> 本图定义「一条生料文本 → 一份鉴定报告（精炼知识对象）」的数据流。
> MVP 只做**单源闭环**；多源矛盾检测、时效判定为规模期（见 PROJECT_PLAN 版本路线）。业务线适配评估已移出炼真（归 Rubedo / OpusMagnum）。
> 分面分类（UDC facet）**不在此图**——那是熔知知识库底层索引代码，由 Citrinitas 完成。

---

## 一、主干流程（MVP 最小闭环）

```mermaid
flowchart TD
    A["Nigredo 生料<br/>字幕/文档文本 + info<br/>(video_id / title / up_name)"] --> B["入站 C1<br/>接收 + 校验"]
    B --> C["内容净化 C2<br/>去广告 / 轻量纠错 / 翻译占位"]
    C --> D{"质量评估 C3<br/>真 / 假 / 可疑"}
    D -->|"虚假"| E["隔离 / 拒入库<br/>(status=rejected)"]
    D -->|"可疑"| F["降权保留 + 黄标<br/>(status=suspect)"]
    D -->|"可信"| G["优点分析 C4<br/>6 子能力萃取"]
    F --> G
    G --> H["结构化提炼 C5<br/>标准 SOP 产出"]
    H --> I["溯源标记 C6<br/>video_id / up / 时间戳"]
    I --> J["精炼知识对象 C7<br/>RefinedKnowledgeObject"]
    J --> K["落本地 data/out/*.json<br/>未来经接口交熔知"]
    E --> K

    style D fill:#fff3cd,stroke:#d39e00
    style J fill:#d4edda,stroke:#28a745
```

**说明**：质量评估是分叉点——虚假直接隔离，可疑降权但保留（不替你拍板），可信才进入优点分析。这三条路径最终都产出 `RefinedKnowledgeObject`，只是 `status` 不同，便于下游（熔知）按可信度分级存储。

---

## 二、节点定义表

| 节点 | 名称 | 输入 | 输出 | 逻辑 | 对应任务 |
|---|---|---|---|---|---|
| C1 | 入站 | Nigredo `process()` 产出的文本（源自各平台，当前以 B站 为主）或用户直接粘贴文本 | `AlbedoInput`（含 text / video_id / title / up_name / source_url） | 校验非空、字段归一 | T1 / T7 / T11 |
| C2 | 内容净化 | `AlbedoInput.text` | `clean_text` | 去广告话术（卖课特征模式库）、轻量 ASR 纠错、多语言翻译占位 | T2 |
| C3 | 质量评估 | `clean_text` + `provenance` | `quality{label, score, reasoning, evidence_grade}` | LLM 单源评估：内部一致性 + 证据具体度 + 卖课话术特征；输出真/假/可疑 + 0-100 分 + 理由 | T3 / T8 |
| C4 | 优点分析 | `clean_text` | `merits{核心洞察, 可复用步骤, 差异化亮点, 适用场景, 陷阱预警, 迁移成本}` | LLM 结构化萃取 6 子能力 | T4 / T8 |
| C5 | 结构化提炼 | `clean_text` + `merits.可复用步骤` | `sop{目的, 前置条件, 编号步骤, 警告, 完成清单}` | 对齐 TubeScribed 标准 SOP 格式，保证 Rubedo 可直接消费 | T5 / T8 |
| C6 | 溯源标记 | Nigredo `info` | `provenance{video_id, up_name, source_url, title, processed_at}` | 精炼阶段即记录来源（天然产物） | T6 |
| C7 | 精炼知识对象 | C2–C6 全部输出 | `RefinedKnowledgeObject`（含 trust_score + status） | 组装 + 由 quality.label 推 status + FPF 轻量信任分 | T1 / T7 |

---

## 三、任务映射（Phase 1 → 节点）

| 任务 | 节点 | 版本归属 |
|---|---|---|
| T1 数据契约 `core/models.py` | C1 / C7 | v0.1.0 |
| T2 内容净化 `core/purify.py` | C2 | v0.1.0 |
| T3 质量评估 `core/assess.py` | C3 | v0.1.0 |
| T7 流水线编排（最小）`flows/refine.py` | C1→C7 | v0.1.0 |
| T8 LLM 调用封装 `core/llm.py` | C3 | v0.1.0 |
| T9 最小 UI `app.py` + `run.bat` | C7 | v0.1.0 |
| T4 优点分析 `core/merit.py` | C4 | v0.2.0 |
| T5 结构化提炼 `core/structure.py` | C5 | v0.2.0 |
| T6 溯源 `core/provenance.py` | C6 | v0.2.0 |
| T7+ 流水线补全 `flows/refine.py` | C1→C7 | v0.2.0 |
| T11 批量/队列（方案A） | C1 | v0.2.0 |

---

## 四、与上下游的接口边界

```
Nigredo ──(字幕 full_text + info)──▶ Albedo ──(RefinedKnowledgeObject)──▶ Citrinitas
                                          │                                      │
                                     只做认知精炼                          只做存储索引
                                     (验真假/提优点/                         (分面分类/
                                      整理步骤/记来源)                       切块/向量化/入库)
```

- **Albedo 不碰**：采集（Nigredo）、分面分类/OCR/切块/向量化/入库（Citrinitas）、创作变现（Rubedo）、意图重写（OpusMagnum）、产品化封装（Rubedo）
- **Albedo 交付物** `RefinedKnowledgeObject` 的 `quality.label` 直接映射熔知 `epistemic_status`（真→corroborated / 可疑→unverified / 假→rejected），`trust_score` 直接填入熔知 payload `trust_score` 字段
- **平台无关**：Albedo 只消费「文字」（Nigredo 产出的生料文本），不绑任何采集平台；当前以 B站 为主，将来 YouTube / 公众号 / 小红书 等来源的文字同样可炼。
