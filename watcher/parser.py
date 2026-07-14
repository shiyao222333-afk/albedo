"""中转①解析：{bv}.md（YAML frontmatter + 正文） → AlbedoInput

依赖自由（不引 pyyaml）：我们的 frontmatter 是简单标量 key:value，
值由 json.dumps 包裹，故做轻量解析即可。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core.models import AlbedoInput


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        try:
            return json.loads(v)
        except Exception:
            return v[1:-1]
    return v


def parse_transit_md(path: str | Path) -> AlbedoInput:
    """读 {bv}.md，解析 frontmatter 字段 + 正文，组装 AlbedoInput。"""
    text = Path(path).read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        # 无 frontmatter：整文件当纯文本
        return AlbedoInput(text=text.strip(), text_type="subtitle")
    meta_block, body = m.group(1), m.group(2)
    fields: dict[str, str] = {}
    for line in meta_block.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        fields[key.strip()] = _unquote(val)
    return AlbedoInput(
        text=body.strip(),
        text_type="subtitle",
        video_id=fields.get("video_id", ""),
        title=fields.get("title", ""),
        up_name=fields.get("up_name", ""),
        source_url=fields.get("source_url", ""),
    )
