"""Locked user-facing copy (VV INT4_DLC_USER_FACING_COPY.md), rendered with MEASURED numbers.

Every size/memory value in here is read from the built artifacts, never typed by
hand.  ``AUTO_DOWNLOAD=FALSE`` / ``USER_CONFIRMATION=REQUIRED`` /
``LITE_CONTINUES_WITHOUT_DLC=TRUE`` are part of the returned payload so a UI can
assert them instead of trusting prose.
"""
from __future__ import annotations

import json
from pathlib import Path

INVARIANTS = {
    "AUTO_DOWNLOAD": "FALSE",
    "USER_CONFIRMATION": "REQUIRED",
    "LITE_CONTINUES_WITHOUT_DLC": "TRUE",
}

INTRO_EN = (
    "**You do not need to install any extension pack to use Solve Lite Lite.**\n"
    "The default Lite Runtime is about 4.6 MB, runs locally on an ordinary CPU, and needs\n"
    "no PyTorch, no Transformers and no model weights at all.\n"
    "The Specialist Add-ons are a completely optional extension for advanced capability. Only\n"
    "install one when you need natural-language inference, financial sentiment analysis,\n"
    "knowledge/topic classification or advanced sentiment judgement.\n"
    "Solve Lite never downloads a DLC automatically. When a task needs a Specialist capability\n"
    "that is not installed, Solve Lite tells you exactly which add-on is needed, the download\n"
    "size and the estimated memory use. Whether to install it is your decision."
)

INTRO_CN = (
    "**无需安装任何扩展包，也可以直接使用 Solve Lite Lite。**\n"
    "默认 Lite Runtime 约 4.6 MB，可直接在普通 CPU 本地运行，无需 PyTorch、Transformers，也无需任何模型权重。\n"
    "Specialist Add-on 是完全可选的高级能力扩展。只有当你需要自然语言推理、金融情绪分析、\n"
    "知识主题分类、高级情感判断等能力时，才需要安装对应扩展。\n"
    "Solve Lite 不会自动下载任何 DLC。当某个任务需要尚未安装的 Specialist 能力时，\n"
    "Solve Lite 会明确告诉你：需要哪个扩展 / 下载大小 / 预计内存占用。是否安装，由你决定。"
)

CLOSING_EN = "Start small. Add only the intelligence you actually need."
CLOSING_CN = "先用最小的版本，只安装你真正需要的智能。"

ADDON_LABELS = {
    "nli": ("NLI", "Natural-language inference", "自然语言推理"),
    "review": ("Sentiment", "Advanced sentiment analysis", "高级情感判断"),
    "topic": ("Topic", "Knowledge/topic routing", "知识主题分类"),
    "financial": ("Finance", "Financial sentiment", "金融情绪分析"),
}


def _mb(value_bytes: int) -> int:
    """Display MB, rounded to the nearest MB (the copy ships whole MB)."""
    return int(round(value_bytes / 1e6))


def addon_table(size_table: dict, route_keys: dict[str, str]) -> list[dict]:
    """Markdown rows + machine fields, sizes straight from the measured table."""
    rows = []
    by_id = {row["dlc_id"]: row for row in size_table["dlcs"]}
    for route, dlc_id in sorted(route_keys.items()):
        row = by_id[dlc_id]
        name_en, capability_en, name_cn = ADDON_LABELS[route]
        rows.append({
            "route": route,
            "dlc_id": dlc_id,
            "addon": name_en,
            "addon_cn": name_cn,
            "capability": capability_en,
            "download_mb": _mb(row["dlc_bytes"]),
            "download_bytes": row["dlc_bytes"],
            "required_by_lite": "No",
            "license_class": row["license_class"],
            "md_row": f"| {name_en} | {capability_en} | {_mb(row['dlc_bytes'])} MB | No |",
        })
    return rows


MEMORY_CALIBER = "DLC_INCREMENT"

#: Peter §0 fixed the displayed caliber at peak - baseline = the DLC increment.
#: VV's template label said "peak memory"; keeping that label over an increment
#: number would mislabel it, so the label follows the caliber.  Every other line
#: of VV's template is reproduced verbatim.
MEMORY_LABEL_EN = "Additional memory when loaded"
MEMORY_LABEL_CN = "加载后额外内存"
PEAK_LABEL_EN = "(process peak memory"
PEAK_LABEL_CN = "（进程峰值内存"


def missing_notice(route: str, download_bytes, memory, lang: str = "en") -> str:
    """Locked 'specialist not installed' prompt (never 'Missing model assets.').

    ``memory`` is the measured profile dict for the route.  A bare number is
    rejected on purpose: the previous peak-caliber call would silently render a
    process peak where the ruling demands the DLC increment.
    """
    if memory is not None and not isinstance(memory, dict):
        raise TypeError("missing_notice() wants the measured memory dict, not a bare MB number")
    name_en, _, name_cn = ADDON_LABELS[route]
    size_mb = _mb(download_bytes)
    memory = memory or {}
    added = memory.get("dlc_increment_mb", "PENDING_MEASUREMENT")
    peak = memory.get("peak_rss_mb")
    if lang == "cn":
        tail = f"{PEAK_LABEL_CN}：{peak} MB）" if peak is not None else ""
        return (
            f"当前任务可以使用可选的 {name_cn} 专业能力扩展。\n"
            "即使不安装，Solve Lite Lite 仍可正常使用。\n"
            f"下载大小：{size_mb} MB\n"
            f"{MEMORY_LABEL_CN}：{added} MB\n"
            f"{tail}\n"
            f"[安装 {name_cn} 扩展]   [暂不安装]"
        )
    tail = f"{PEAK_LABEL_EN}: {peak} MB)" if peak is not None else ""
    return (
        f"This task can use the optional {name_en} Specialist Add-on.\n"
        "Solve Lite Lite will continue to work without it.\n"
        f"Download size: {size_mb} MB\n"
        f"{MEMORY_LABEL_EN}: {added} MB\n"
        f"{tail}\n"
        f"[Install {name_en} Add-on]   [Not now]"
    )


def memory_profile_entry(peak_row: dict) -> dict:
    """One route of evidence/memory/PEAK_BY_ROUTE.json -> the shipped profile row.

    Caliber is Peter §0: increment = peak - baseline.  ``baseline`` is the RSS of
    the same process BEFORE the DLC is loaded (peak_memory_probe measures both).
    """
    peak = int(peak_row["peak_rss_bytes"])
    base = int(peak_row["rss_before_bytes"])
    return {
        "baseline_rss_bytes": base,
        "peak_rss_bytes": peak,
        "dlc_increment_bytes": peak - base,
        "dlc_increment_mb": _mb(peak - base),
        "peak_rss_mb": _mb(peak),
        "caliber": MEMORY_CALIBER,
        "cases": peak_row.get("cases"),
    }


def load_size_table(stage: Path) -> dict:
    return json.loads((Path(stage) / "dlc-build" / "SIZE_TABLE.json").read_text(encoding="utf-8"))
