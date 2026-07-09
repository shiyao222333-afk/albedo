"""Albedo (Lian Zhen) · LLM 调用封装 (C3 复用)

对齐 熔知 search_engine.answer._call_llm_api 约定：
  - env: KB_LLM_BASE_URL / KB_LLM_API_KEY / KB_LLM_MODEL
  - 默认 base_url = https://api.deepseek.com/v1, model = deepseek-chat
  - OpenAI 兼容 /chat/completions 接口，temperature=0 确定性输出
  - 结构化输出借鉴 熔知 utils.llm_helpers.extract_json_block 的花括号深度匹配容错

将来 熔知 改了这套约定，这里需同步改（已在 PROJECT_PLAN §5.2 标注）。
"""
from __future__ import annotations

import json
import os
import re

# 若项目根存在 .env，优先加载（不强制依赖 python-dotenv）
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import requests

LLM_BASE_URL = os.environ.get("KB_LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_API_KEY = os.environ.get("KB_LLM_API_KEY", "")
LLM_MODEL = os.environ.get("KB_LLM_MODEL", "deepseek-chat")


def call_llm(
    messages: list,
    *,
    base_url: str = None,
    api_key: str = None,
    model: str = None,
    max_tokens: int = 2048,
    timeout: int = 120,
) -> str:
    """调用 OpenAI 兼容 Chat API，返回模型回复文本。"""
    base_url = (base_url or LLM_BASE_URL).rstrip("/")
    api_key = api_key or LLM_API_KEY
    model = model or LLM_MODEL
    if not api_key:
        raise RuntimeError(
            "未配置 LLM API。请设置环境变量 KB_LLM_API_KEY（或项目根 .env 文件）。"
        )
    resp = requests.post(
        f"{base_url}/chat/completions",
        json={
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
        },
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def extract_json_block(text: str):
    """从 LLM 返回文本中提取并解析 JSON 对象（支持嵌套）。

    策略（与 熔知 utils.llm_helpers.extract_json_block 一致）：
      1. 直接 json.loads()
      2. 失败则匹配花括号深度，提取最外层 JSON
      3. 去掉尾部逗号后重试
    返回 dict；无法解析时返回 None。
    """
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False
    json_end = -1

    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and not in_string:
            in_string = True
            continue
        if in_string:
            if ch == '"':
                in_string = False
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                json_end = i + 1
                break

    if json_end == -1:
        return None

    json_block = text[start:json_end]
    try:
        return json.loads(json_block)
    except json.JSONDecodeError:
        json_block = re.sub(r",\s*}", "}", json_block)
        json_block = re.sub(r",\s*\]", "]", json_block)
        try:
            return json.loads(json_block)
        except json.JSONDecodeError:
            return None


def call_llm_json(messages: list, **kwargs) -> dict:
    """call_llm + extract_json_block 的组合；解析失败抛 RuntimeError。"""
    raw = call_llm(messages, **kwargs)
    data = extract_json_block(raw)
    if data is None:
        raise RuntimeError(f"LLM 未返回可解析 JSON。原始回复前 200 字：{raw[:200]}")
    return data
