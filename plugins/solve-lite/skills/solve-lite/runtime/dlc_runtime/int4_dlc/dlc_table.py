"""Single source of truth for the four INT4 DLC units.

``asset_rel`` is the path a model directory must occupy inside a Lite
``asset_root`` (see solve_lite.lite_runtime.capability: the asset root contains
``model-cache/<hf-dir>`` for four families and
``model-cache-public-trained/financial_sentiment`` for the tuned financial
checkpoint).  ``dlc_rel`` is the same directory inside the DLC package.

Licence discipline (VV ruling, INT4_DLC_TASK.md section 2 -- verbatim):

    DBpedia14 / SST-2 / DeBERTa-NLI = Apache-2.0   -> official DLC
    ProsusAI/finbert + local tuned financial model -> licence unclear
        -> int4 engineering verification only, weights must never be uploaded

The two financial checkpoints are therefore packaged as one ENGINEERING-ONLY
unit.  They are also indivisible for a second, mechanical reason: the frozen
kernel's ``process_financial`` loads BOTH checkpoints before either forward pass
(BUILD/lite_src/_src5_lite.py:174-175), so splitting them would either break the
route or defeat "one DLC at a time".
"""

from __future__ import annotations

from .format import LICENSE_ENGINEERING_ONLY, LICENSE_OFFICIAL_APACHE2

DLC_UNITS: list[dict] = [
    {
        "dlc_id": "review-sst2-distilbert-int4-g64",
        "family": "review",
        "route": "review",
        "arch": "DistilBertForSequenceClassification",
        "params_note": "distilbert-base-uncased-finetuned-sst-2-english",
        "license_class": LICENSE_OFFICIAL_APACHE2,
        "license_spdx": "Apache-2.0",
        "source_repo": "distilbert/distilbert-base-uncased-finetuned-sst-2-english",
        "license_evidence": "README.md frontmatter: license: apache-2.0",
        "members": [
            {
                "asset_rel": "model-cache/distilbert--distilbert-base-uncased-finetuned-sst-2-english",
                "dlc_rel": "model-cache/distilbert--distilbert-base-uncased-finetuned-sst-2-english",
                "source_rel": "model-cache/distilbert--distilbert-base-uncased-finetuned-sst-2-english",
                "build_id": "sst2-distilbert-int4-g64",
            }
        ],
    },
    {
        "dlc_id": "topic-dbpedia14-bert-int4-g64",
        "family": "topic",
        "route": "topic",
        "arch": "BertForSequenceClassification",
        "params_note": "bert-base-uncased fine-tuned on DBpedia14 (14 labels)",
        "license_class": LICENSE_OFFICIAL_APACHE2,
        "license_spdx": "Apache-2.0",
        "source_repo": "fabriceyhc/bert-base-uncased-dbpedia_14",
        "license_evidence": "README.md frontmatter: license: apache-2.0",
        "members": [
            {
                "asset_rel": "model-cache/fabriceyhc--bert-base-uncased-dbpedia_14",
                "dlc_rel": "model-cache/fabriceyhc--bert-base-uncased-dbpedia_14",
                "source_rel": "model-cache/fabriceyhc--bert-base-uncased-dbpedia_14",
                "build_id": "dbpedia14-bert-base-int4-g64",
            }
        ],
    },
    {
        "dlc_id": "nli-deberta-v3-base-int4-g64",
        "family": "nli",
        "route": "nli",
        "arch": "DebertaV2ForSequenceClassification",
        "params_note": "cross-encoder/nli-deberta-v3-base (SNLI+MultiNLI)",
        "license_class": LICENSE_OFFICIAL_APACHE2,
        "license_spdx": "Apache-2.0",
        "source_repo": "cross-encoder/nli-deberta-v3-base",
        "license_evidence": "README.md frontmatter: license: apache-2.0",
        "members": [
            {
                "asset_rel": "model-cache/cross-encoder--nli-deberta-v3-base",
                "dlc_rel": "model-cache/cross-encoder--nli-deberta-v3-base",
                "source_rel": "model-cache/cross-encoder--nli-deberta-v3-base",
                "build_id": "nli-deberta-v3-base-int4-g64",
            }
        ],
    },
    {
        "dlc_id": "financial-pair-int4-g64-ENGINEERING-ONLY",
        "family": "financial",
        "route": "financial",
        "arch": "BertForSequenceClassification (x2)",
        "params_note": "ProsusAI/finbert + public-trained financial_sentiment, co-required by the frozen route",
        "license_class": LICENSE_ENGINEERING_ONLY,
        "license_spdx": "UNKNOWN_PENDING_UPSTREAM",
        "source_repo": "ProsusAI/finbert + local/public-trained financial_sentiment",
        "license_evidence": (
            "ProsusAI/finbert README.md has no license field (tags only); "
            "financial_sentiment ships no README and no HF download metadata"
        ),
        "distributable": False,
        "members": [
            {
                "asset_rel": "model-cache/ProsusAI--finbert",
                "dlc_rel": "model-cache/ProsusAI--finbert",
                "source_rel": "model-cache/ProsusAI--finbert",
                "build_id": "finbert-int4-g64-ENGINEERING",
            },
            {
                "asset_rel": "model-cache-public-trained/financial_sentiment",
                "dlc_rel": "model-cache-public-trained/financial_sentiment",
                "source_rel": "model-cache-public-trained/financial_sentiment",
                "build_id": "financial-public-trained-int4-g64-ENGINEERING",
            },
        ],
    },
]

#: tokenizer / config files that must travel with a DLC (everything except weights)
CARRIED_FILES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "vocab.txt",
    "vocab.json",
    "merges.txt",
    "spm.model",
    "sentencepiece.bpe.model",
)


def unit_by_id(dlc_id: str) -> dict:
    for unit in DLC_UNITS:
        if unit["dlc_id"] == dlc_id:
            return unit
    raise KeyError(f"UNKNOWN_DLC_ID: {dlc_id}")


def official_units() -> list[dict]:
    return [unit for unit in DLC_UNITS if unit["license_class"] == LICENSE_OFFICIAL_APACHE2]


def engineering_units() -> list[dict]:
    return [unit for unit in DLC_UNITS if unit.get("distributable", True) is False]
