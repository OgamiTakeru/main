import datetime


class OpposingPositionPolicy:
    """Decide how a new order interacts with opposite open trades."""

    DEFAULTS = {
        "stale_minutes": 60,
        "recovery_unlikely_loss_yen": 10.0,
        "strong_score": 0.80,
        "strong_priority": 10.0,
        "strong_condition_count": 2,
    }
    PAIR_OVERRIDES = {
        "USD_JPY": {},
        "EUR_USD": {},
        "AUD_USD": {},
    }

    def __init__(self, pair, now=None):
        self.pair = pair
        self.now = now or datetime.datetime.now(datetime.timezone.utc)
        self.settings = {
            **self.DEFAULTS,
            **self.PAIR_OVERRIDES.get(pair, {}),
        }

    @staticmethod
    def _owner_tag(trade):
        """建玉に付いている所有タグを読む（無ければ None）。"""
        extensions = trade.get("clientExtensions")
        if not isinstance(extensions, dict):
            return None
        tag = extensions.get("tag")
        return str(tag) if tag is not None else None

    @classmethod
    def is_protected(cls, trade):
        """所有タグ付きの建玉は、他の注文の都合で触ってはいけない。

        タグ付きの建玉は、それを出した解析が自分の決済条件（利確・損切り・
        保有時間）で最後まで面倒を見る前提で建てられている。別の注文の
        逆ポジ判定でここを決済すると、その前提が崩れる。両建てのまま
        並走させ、決済は持ち主に任せる。
        """
        return cls._owner_tag(trade) is not None

    def evaluate(self, order_plan, open_trades):
        direction = self._sign(order_plan.get("direction"))
        opposite = [
            trade for trade in open_trades
            if trade.get("instrument") == self.pair
            and self._sign(trade.get("currentUnits")) == -direction
            and not self.is_protected(trade)
        ]
        if not opposite:
            return self._decision("allow", "no_opposite_position", [])

        profitable = [
            trade for trade in opposite
            if self._float(trade.get("unrealizedPL")) > 0
        ]
        if profitable:
            return self._decision(
                "take_profit_and_block",
                "opposite_position_is_profitable",
                profitable,
            )

        losing = [
            trade for trade in opposite
            if self._float(trade.get("unrealizedPL")) < 0
        ]
        if len(losing) != len(opposite):
            return self._decision(
                "block",
                "opposite_position_is_flat",
                [],
                opposite,
            )

        stale_seconds = self.settings["stale_minutes"] * 60
        if any(self._elapsed_seconds(trade) < stale_seconds for trade in losing):
            return self._decision(
                "block",
                "opposite_loss_is_not_stale",
                [],
                losing,
            )

        total_loss_yen = -sum(
            self._float(trade.get("unrealizedPL")) for trade in losing
        )
        if total_loss_yen < self.settings["recovery_unlikely_loss_yen"]:
            return self._decision(
                "block",
                "opposite_loss_not_large_enough_to_reverse",
                [],
                losing,
            )

        strength = self.signal_strength(order_plan)
        if not strength["is_strong"]:
            return self._decision(
                "block",
                "new_signal_is_not_strong",
                [],
                losing,
                strength,
            )

        return self._decision(
            "stop_and_reverse",
            "stale_opposite_loss_and_strong_new_signal",
            losing,
            losing,
            strength,
        )

    def signal_strength(self, order_plan):
        entry_type = order_plan.get("line_entry_type")
        score_key = (
            "line_resist_score" if entry_type == "reversal"
            else "line_break_score"
        )
        score = self._optional_float(order_plan.get(score_key))
        priority = self._float(order_plan.get("priority"))
        condition_count = self._condition_count(order_plan.get("memo"))
        score_is_strong = (
            score is not None and score >= self.settings["strong_score"]
        )
        fallback_is_strong = (
            priority >= self.settings["strong_priority"]
            and condition_count >= self.settings["strong_condition_count"]
        )
        return {
            "is_strong": score_is_strong or fallback_is_strong,
            "score_key": score_key,
            "score": score,
            "priority": priority,
            "condition_count": condition_count,
        }

    def _decision(
        self,
        action,
        reason,
        close_trades,
        opposite_trades=None,
        strength=None,
    ):
        opposite_trades = opposite_trades or close_trades
        return {
            "action": action,
            "reason": reason,
            "close_trades": close_trades,
            "opposite_trades": opposite_trades,
            "total_unrealized_pl": sum(
                self._float(trade.get("unrealizedPL"))
                for trade in opposite_trades
            ),
            "max_elapsed_minutes": max(
                (self._elapsed_seconds(trade) / 60 for trade in opposite_trades),
                default=0,
            ),
            "strength": strength or self.signal_strength({}),
        }

    def _elapsed_seconds(self, trade):
        if trade.get("past_time_sec") is not None:
            return max(self._float(trade.get("past_time_sec")), 0)
        opened = trade.get("openTime")
        if not opened:
            return 0
        try:
            open_dt = datetime.datetime.fromisoformat(
                str(opened).replace("Z", "+00:00")
            )
        except ValueError:
            return 0
        now = self.now
        if now.tzinfo is None:
            now = now.replace(tzinfo=datetime.timezone.utc)
        if open_dt.tzinfo is None:
            open_dt = open_dt.replace(tzinfo=datetime.timezone.utc)
        return max((now - open_dt).total_seconds(), 0)

    @staticmethod
    def _condition_count(memo):
        if not memo or "reason=" not in str(memo):
            return 0
        reasons = str(memo).split("reason=", 1)[1]
        return len([reason for reason in reasons.split(" / ") if reason.strip()])

    @staticmethod
    def _sign(value):
        number = float(value or 0)
        if number == 0:
            return 0
        return 1 if number > 0 else -1

    @staticmethod
    def _float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _optional_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
