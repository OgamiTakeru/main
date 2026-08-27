# 最新更新日時: 2026-08-27 JST
"""Frozen per-pair live policies for ``flip_predict``, loaded from artifacts.

The live service must trade exactly the policy that was selected on train and
verified on the following out-of-sample year -- never a hand-typed variant of
it.  Each policy here is therefore read from its analysis artifact at import
time and checked against the SHA-256 that was recorded when the policy was
approved, so editing the artifact, or pointing at a newer one, fails loudly
instead of silently changing what the account trades.

To adopt a newly verified artifact: rerun the analysis, confirm the
out-of-sample result, then update that pair's ``artifact_sha256`` below.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import tokens as tk
from count2_flip_core import (
    FlipWatchEntryConfig,
    RankedPolicyCondition,
    RiskMultipleProfitLock,
    TierExecutionConfig,
)


POLICY_VERSION = "flip_predict_v19"
TRAIN_START = dt.datetime(2023, 7, 30)
TRAIN_END = dt.datetime(2025, 7, 30)
OOS_START = dt.datetime(2025, 7, 30)
OOS_END = dt.datetime(2026, 7, 30)


def artifact_path(pair: str, folder: Path | None = None) -> Path:
    stem = (
        f"{POLICY_VERSION}_{pair}_{TRAIN_START:%Y%m%d}_{TRAIN_END:%Y%m%d}"
        f"_to_{OOS_START:%Y%m%d}_{OOS_END:%Y%m%d}_artifact.json"
    )
    return Path(folder or tk.folder_path) / stem


@dataclass(frozen=True)
class LivePairPolicy:
    """Everything the live loop needs to trade one pair, frozen together."""

    pair: str
    owner_tag: str
    state_filename: str
    artifact_sha256: str
    ranked_conditions: tuple[RankedPolicyCondition, ...]
    tier_configs: tuple[TierExecutionConfig, ...]
    watch_config: FlipWatchEntryConfig
    minimum_matched_conditions: int
    profit_lock: RiskMultipleProfitLock | None
    profit_lock_tiers: frozenset[str]

    @property
    def tier_by_name(self) -> dict[str, TierExecutionConfig]:
        return {config.tier: config for config in self.tier_configs}

    def locks_tier(self, tier: str) -> bool:
        """Whether the raised stop applies to ``tier``.

        A tier whose RR sits at or below the trigger runs unlocked, because
        the stop could only have moved after the take-profit already closed
        the trade.  The analysis records which tiers qualified.
        """
        return self.profit_lock is not None and tier in self.profit_lock_tiers

    def fingerprint(self) -> str:
        """Stable hash of what is actually traded, for logs and notices."""
        payload = {
            "version": POLICY_VERSION,
            "pair": self.pair,
            "artifact_sha256": self.artifact_sha256,
            "minimum_matched_conditions": self.minimum_matched_conditions,
            "profit_lock": (
                self.profit_lock.to_dict() if self.profit_lock else None
            ),
            "profit_lock_tiers": sorted(self.profit_lock_tiers),
            "tiers": [config.to_dict() for config in self.tier_configs],
            "conditions": [
                item.to_dict() for item in self.ranked_conditions
            ],
            "watch": self.watch_config.to_dict(),
        }
        return hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()


def _load_artifact(pair: str, expected_sha256: str) -> Mapping[str, Any]:
    path = artifact_path(pair)
    if not path.exists():
        raise FileNotFoundError(
            f"{pair} live policy needs its analysis artifact: {path}"
        )
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest().upper()
    if actual != expected_sha256.upper():
        raise ValueError(
            f"{pair} artifact does not match the approved policy.\n"
            f"  expected sha256: {expected_sha256.upper()}\n"
            f"  actual sha256:   {actual}\n"
            f"  path: {path}\n"
            "Rerun the analysis, confirm the out-of-sample result, then "
            "update artifact_sha256 in fFlipPredictPolicy.py."
        )
    return json.loads(raw.decode("utf-8"))


def load_pair_policy(
    pair: str,
    *,
    owner_tag: str,
    state_filename: str,
    artifact_sha256: str,
) -> LivePairPolicy:
    """Build one pair's live policy from its verified artifact."""
    artifact = _load_artifact(pair, artifact_sha256)
    if artifact["version"] != POLICY_VERSION:
        raise ValueError(
            f"{pair} artifact is {artifact['version']}, expected {POLICY_VERSION}"
        )
    if artifact["pair"] != pair:
        raise ValueError(f"artifact pair {artifact['pair']} is not {pair}")
    top_policy = artifact["top_condition_policy"]
    lock_spec = top_policy.get("risk_multiple_profit_lock")
    ranked = tuple(
        RankedPolicyCondition.from_dict(item)
        for item in artifact["selected_top_conditions"]
    )
    expected_count = int(artifact["top_condition_limit"])
    if len(ranked) != expected_count:
        raise ValueError(
            f"{pair} artifact lists {len(ranked)} conditions, expected "
            f"{expected_count}"
        )
    return LivePairPolicy(
        pair=pair,
        owner_tag=owner_tag,
        state_filename=state_filename,
        artifact_sha256=artifact_sha256.upper(),
        ranked_conditions=ranked,
        tier_configs=tuple(
            TierExecutionConfig.from_dict(item)
            for item in artifact["tier_execution_configs"]
        ),
        watch_config=FlipWatchEntryConfig.from_dict(
            artifact["execution"]["watch_entry"]
        ),
        minimum_matched_conditions=int(
            top_policy["minimum_matched_conditions"]
        ),
        profit_lock=(
            RiskMultipleProfitLock(
                trigger_r=float(lock_spec["trigger_r"]),
                result_r=float(lock_spec["result_r"]),
            )
            if lock_spec
            else None
        ),
        profit_lock_tiers=frozenset(
            top_policy.get("risk_multiple_profit_lock_tiers") or ()
        ),
    )


# Approved artifacts.  A pair only appears here once its out-of-sample year
# has been reviewed; the SHA pins the exact file that review covered.
#
#   EUR_USD  OOS n=50  win 50.0%  PF 1.10  +121 yen
#   AUD_USD  OOS n=51  win 52.9%  PF 1.25  +271 yen
#
# USD_JPY is deliberately absent: its conditions barely overlap, so the
# agreement threshold leaves it with almost no trades.  See
# memo/flip_predict_todo.md before adding it.
APPROVED_PAIRS: dict[str, dict[str, str]] = {
    "EUR_USD": {
        "owner_tag": "flip_predict_eur",
        "state_filename": "flip_predict_eur_usd_v19.json",
        "artifact_sha256": (
            "0A0704B1ABB9E3FDD89346CBEC44CAD3F59F69245DB007D27B0B7E199EF66954"
        ),
    },
    "AUD_USD": {
        "owner_tag": "flip_predict_aud",
        "state_filename": "flip_predict_aud_usd_v19.json",
        "artifact_sha256": (
            "1B26F7BA3035565628D0DC88773AEED7AC1367FE845768FA7D948C915C12406C"
        ),
    },
}


def live_policy(pair: str) -> LivePairPolicy:
    """Return the approved live policy for ``pair``.

    Raises for a pair that has not been approved, so a typo or an untested
    pair can never reach the order path.
    """
    key = str(pair).upper()
    spec = APPROVED_PAIRS.get(key)
    if spec is None:
        raise ValueError(
            f"{key} has no approved flip_predict live policy. Approved: "
            + ", ".join(sorted(APPROVED_PAIRS))
        )
    return load_pair_policy(key, **spec)
