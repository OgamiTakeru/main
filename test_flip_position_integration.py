# 最新更新日時: 2026-08-29 19:26 JST
"""flip をポジションスロットで管理するための土台のテスト。

ここで守りたいのは次の三つ。
  - classPosition は出自を運ぶが、その意味は解釈しない
  - 出自ごとの待機処理は、その解析のファイル側に委譲される
  - 委譲先が判断できない間は、勝手に発注しない
"""

import datetime
import types
import unittest
import unittest.mock

import pandas as pd

import classPosition
import fFlipOrder
import fFlipPredictPolicy as flip_policy
import fFlipWatch
import fGeneric as gene


class OriginRegistryTest(unittest.TestCase):
    def test_flip_handler_is_registered(self):
        self.assertIs(
            classPosition.ORIGIN_WATCH_HANDLERS.get(fFlipWatch.ORIGIN),
            fFlipWatch.watch,
        )

    def test_duplicate_registration_is_refused(self):
        def other(position, candle):
            return 0

        with self.assertRaisesRegex(ValueError, "二重登録"):
            classPosition.register_origin_watch_handler(
                fFlipWatch.ORIGIN, other
            )
        # 同じ関数の再登録は冪等なので許す（モジュール再読込に耐えるため）。
        classPosition.register_origin_watch_handler(
            fFlipWatch.ORIGIN, fFlipWatch.watch
        )

    def test_empty_origin_is_refused(self):
        with self.assertRaises(ValueError):
            classPosition.register_origin_watch_handler("", lambda p, c: 0)


def _s5(times_and_prices):
    """時刻降順（共有フレームと同じ並び）の S5 フレームを作る。"""
    rows = []
    for stamp, o, h, l, c in times_and_prices:
        rows.append(
            {
                "time_jp": stamp,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "is_complete": True,
            }
        )
    frame = pd.DataFrame(rows)
    return types.SimpleNamespace(
        s5_completed_df_r=frame.iloc[::-1].reset_index(drop=True)
    )


class FlipWatchTest(unittest.TestCase):
    def _position(self, line_price=150.0, peak_direction=1):
        position = types.SimpleNamespace()
        position.pair = "USD_JPY"
        position.plan_json = {
            "flip_line_price": line_price,
            "flip_peak_direction": peak_direction,
            "flip_average_range_pips": 5.0,
            "flip_spread_pips": 0.8,
            "flip_observation_seconds": 60,
        }
        position.waiting_order = True
        position.watching_for_position_done = False
        position.o_state = "Watching"
        position.order_register_time = datetime.datetime(
            2025,
            1,
            6,
            8,
            59,
            59,
        )
        position.placed = []
        position.make_order = lambda: (
            position.placed.append("order") or {"order_id": 1}
        )
        return position

    def test_no_touch_keeps_waiting_and_places_nothing(self):
        position = self._position()
        base = datetime.datetime(2025, 1, 6, 9, 0, 0)
        # ラインに遠く届かない値動き。
        bars = [
            (base + datetime.timedelta(seconds=5 * i), 149.0, 149.1, 148.9, 149.0)
            for i in range(5)
        ]
        result = fFlipWatch.watch(position, _s5(bars))
        self.assertEqual(result, 0)
        self.assertTrue(position.waiting_order)
        self.assertFalse(position.watching_for_position_done)
        self.assertEqual(position.flip_watch_state["phase"], "PENDING_TOUCH")

    def test_touch_places_the_order_immediately(self):
        # 検証（OOS）と同じ挙動: タッチしたらその場で発注する。
        position = self._position()
        base = datetime.datetime(2025, 1, 6, 9, 0, 0)
        bars = [
            (base, 149.9, 149.95, 149.85, 149.9),
            (base + datetime.timedelta(seconds=5), 149.95, 150.05, 149.9, 150.0),
        ]
        fFlipWatch.watch(position, _s5(bars))
        self.assertEqual(position.flip_watch_state["phase"], "DONE")
        self.assertIsNotNone(position.flip_watch_state["touch_time"])
        self.assertEqual(position.placed, ["order"])
        self.assertFalse(position.waiting_order)
        self.assertTrue(position.watching_for_position_done)

    def test_touch_uses_the_spread_aware_wick(self):
        # ライン 150.0 に対し高値 149.999 でも、スプレッド分を見込むと届かない。
        position = self._position(line_price=150.0, peak_direction=1)
        base = datetime.datetime(2025, 1, 6, 9, 0, 0)
        fFlipWatch.watch(
            position, _s5([(base, 149.9, 149.999, 149.9, 149.95)])
        )
        self.assertEqual(position.placed, [])
        self.assertEqual(position.flip_watch_state["phase"], "PENDING_TOUCH")

    def test_state_is_cleared_between_slot_uses(self):
        position = self._position()
        position.flip_watch_state = {"phase": "DONE", "bars": []}
        fFlipWatch.clear_flip_state(position)
        self.assertFalse(hasattr(position, "flip_watch_state"))

    def test_unknown_origin_never_orders(self):
        position = classPosition.order_information("t", False)
        position.origin = "not_registered"
        position.watching_for_position_done = False
        self.assertEqual(position.watching_for_position_by_origin(None), 0)


def _fake_candle():
    """Order / classPosition が参照する candle_analysis_class の最小形。"""
    meta = types.SimpleNamespace(cal_move_ave=lambda n: 0.0)
    peaks = types.SimpleNamespace(
        peaks_original=[{"latest_body_peak_price": 0.6500}]
    )
    basic_analysis = types.SimpleNamespace(
        m5_peaks_class=peaks,
        h1_peaks_class=peaks,
    )
    return types.SimpleNamespace(
        candle_meta_class=meta,
        candle_meta_class_hour=meta,
        current_price=0.6500,
        basic_analysis=basic_analysis,
        require_basic_analysis=lambda: basic_analysis,
        peaks_class=peaks,
        peaks_class_hour=peaks,
    )


def _signal(**overrides):
    signal = {
        "signal_tier": "HIGH",
        "highest_matched_rank": 1,
        "tp_pips": 15.0,
        "lc_pips": 10.5,
        "line_price": 0.6500,
        "order_direction": 1,
        "peak_direction": -1,
        "a_range_pips": 7.5,
        "decision_time_utc": "2026-08-27T00:00:00+00:00",
        "signal_id": "fp_test",
    }
    signal.update(overrides)
    return signal


class FlipOrderTest(unittest.TestCase):
    def setUp(self):
        self.policy = flip_policy.live_policy("AUD_USD")

    def test_raised_stop_becomes_lc_change_in_price_terms(self):
        # LC 10pips のトレードなら、+12.0p で発動し +10.5p を確保する。
        rows = fFlipOrder.raised_stop_lc_change(self.policy, 10.0)
        self.assertEqual(len(rows), 1)
        pair_info = gene.currency_pair("AUD_USD")
        self.assertAlmostEqual(
            pair_info.price_to_pips(rows[0]["trigger"]), 12.0, places=6
        )
        self.assertAlmostEqual(
            pair_info.price_to_pips(rows[0]["ensure"]), 10.5, places=6
        )
        # 確保する側は必ず発動より内側でなければならない。
        self.assertLess(rows[0]["ensure"], rows[0]["trigger"])

    def test_no_policy_lock_means_no_lc_change(self):
        self.assertEqual(fFlipOrder.raised_stop_lc_change(None, 10.0), [])

    def test_zero_lc_is_refused_rather_than_dividing(self):
        self.assertEqual(fFlipOrder.raised_stop_lc_change(self.policy, 0.0), [])

    def test_order_carries_origin_and_flip_watch_inputs(self):
        order = fFlipOrder.build_order(
            _signal(), "AUD_USD", _fake_candle(), policy=self.policy, oa=None
        )
        plan = order.exe_order_plan
        self.assertEqual(plan["origin"], fFlipOrder.ORIGIN)
        self.assertEqual(plan["owner_tag"], self.policy.owner_tag)
        # 見張りに必要な情報が注文に同梱されていること。
        for key in (
            "flip_line_price",
            "flip_peak_direction",
            "flip_average_range_pips",
            "flip_observation_seconds",
        ):
            self.assertIn(key, order.order_json)
        # 待機として登録され、リスクから units が決まっていること。
        self.assertGreater(plan["units"], 0)
        self.assertTrue(plan["lc_change"])

    def test_usd_jpy_needs_no_cross_rate(self):
        self.assertIsNone(fFlipOrder.usd_jpy_rate_for("USD_JPY", None))
        # クロス通貨は取得できなければ既定値に落ちる（注文は落とさない）。
        self.assertEqual(
            fFlipOrder.usd_jpy_rate_for("AUD_USD", None),
            fFlipOrder.FALLBACK_USD_JPY_RATE,
        )


class RealRegistrationPathTest(unittest.TestCase):
    """偽オブジェクトではなく、実際の order_plan_registration を通す。

    最初の実装はこの経路を通していなかったため、order_permission が既定の
    True になり「登録した瞬間に発注される」欠陥を検出できなかった。
    """

    def setUp(self):
        self.policy = flip_policy.live_policy("AUD_USD")
        self.order = fFlipOrder.build_order(
            _signal(), "AUD_USD", _fake_candle(), policy=self.policy, oa=None
        )

    def test_flip_order_is_registered_as_waiting_not_placed(self):
        # ここが本丸: 登録しても発注されず、待機に入ること。
        self.assertIs(self.order.exe_order_plan["order_permission"], False)

        position = classPosition.order_information("slot", False)
        placed = []
        with unittest.mock.patch.object(
            classPosition.order_information,
            "make_order",
            lambda self: placed.append(self.name) or {"order_id": 1},
        ):
            position.order_plan_registration(self.order)

        self.assertEqual(placed, [], "登録だけで発注されてはいけない")
        self.assertTrue(position.waiting_order)
        self.assertEqual(position.o_state, "Watching")
        self.assertEqual(position.origin, fFlipOrder.ORIGIN)
        self.assertEqual(position.owner_tag, self.policy.owner_tag)

    def test_api_order_carries_owner_tag_and_open_only(self):
        order = self.order.data["order"]
        self.assertEqual(
            order["clientExtensions"]["tag"], self.policy.owner_tag
        )
        self.assertEqual(
            order["tradeClientExtensions"]["tag"], self.policy.owner_tag
        )
        # 既存建玉を相殺せず、必ず新規で開く。
        self.assertEqual(order["positionFill"], "OPEN_ONLY")

    def test_reset_clears_the_flip_watch_state(self):
        position = classPosition.order_information("slot", False)
        position.flip_watch_state = {"phase": "DONE", "bars": [1, 2, 3]}
        position.reset()
        self.assertFalse(hasattr(position, "flip_watch_state"))

    def test_waiting_order_expires_and_frees_the_slot(self):
        position = classPosition.order_information("slot", False)
        position.origin = fFlipOrder.ORIGIN
        position.waiting_order = True
        position.watching_for_position_done = False
        position.order_timeout_min = 60
        # 61 分前に登録された待機として扱う。
        position.order_register_time = (
            datetime.datetime.now() - datetime.timedelta(minutes=61)
        )
        self.assertTrue(position.waiting_order_expired())
        position.watching_for_position_by_origin(None)
        self.assertFalse(position.waiting_order)
        self.assertTrue(position.watching_for_position_done)
        self.assertFalse(position.life)

    def test_waiting_order_within_limit_is_kept(self):
        position = classPosition.order_information("slot", False)
        position.origin = fFlipOrder.ORIGIN
        position.waiting_order = True
        position.order_timeout_min = 60
        position.order_register_time = (
            datetime.datetime.now() - datetime.timedelta(minutes=5)
        )
        self.assertFalse(position.waiting_order_expired())


class WaitingOrderOpposingPolicyTest(unittest.TestCase):
    def test_waiting_order_defers_the_opposing_decision(self):
        # 待機注文は、反対建玉の早期決済を引き起こしてはいけない。
        import classPositionControl

        control = classPositionControl.position_control.__new__(
            classPositionControl.position_control
        )
        control.is_live = True
        control.pair = "AUD_USD"
        control.oa2 = types.SimpleNamespace(
            OpenTrades_exe=lambda: {
                "error": 0,
                "json": {
                    "trades": [
                        {
                            "instrument": "AUD_USD",
                            "currentUnits": "-100",
                            "unrealizedPL": "50",
                        }
                    ]
                },
            }
        )
        order = fFlipOrder.build_order(
            _signal(order_direction=1),
            "AUD_USD",
            _fake_candle(),
            policy=flip_policy.live_policy("AUD_USD"),
            oa=None,
        )
        allowed = control.apply_opposing_position_policy([order])
        self.assertEqual(len(allowed), 1)
        self.assertEqual(
            order.exe_order_plan["opposing_position_action"],
            "deferred_until_order",
        )


class OwnedTradeProtectionTest(unittest.TestCase):
    """タグ付き建玉が、他の注文の都合で決済されないこと。"""

    def _trade(self, tag=None, units="-100", pl="50"):
        trade = {
            "instrument": "AUD_USD",
            "currentUnits": units,
            "unrealizedPL": pl,
        }
        if tag is not None:
            trade["clientExtensions"] = {"tag": tag}
        return trade

    def test_tagged_opposite_trade_is_not_closed(self):
        import classOpposingPositionPolicy as opp

        policy = opp.OpposingPositionPolicy("AUD_USD")
        # タグ無しの利益の乗った逆ポジは、従来どおり利確対象。
        plain = policy.evaluate({"direction": 1}, [self._trade()])
        self.assertEqual(plain["action"], "take_profit_and_block")

        # タグ付きなら、逆ポジとして見えず両建てのまま通す。
        owned = policy.evaluate(
            {"direction": 1}, [self._trade(tag="flip_predict_aud")]
        )
        self.assertEqual(owned["action"], "allow")
        self.assertEqual(owned["reason"], "no_opposite_position")

    def test_is_protected_reads_the_tag(self):
        import classOpposingPositionPolicy as opp

        self.assertFalse(opp.OpposingPositionPolicy.is_protected(self._trade()))
        self.assertTrue(
            opp.OpposingPositionPolicy.is_protected(
                self._trade(tag="flip_predict_eur")
            )
        )

    def test_hedge_closing_skips_owned_positions(self):
        import classPositionControl

        control = classPositionControl.position_control.__new__(
            classPositionControl.position_control
        )
        closed = []

        def _slot(name, direction, pl, owner_tag=""):
            slot = types.SimpleNamespace()
            slot.life = True
            slot.name = name
            slot.owner_tag = owner_tag
            slot.t_unrealize_pl = pl
            slot.plan_json = {"target_price": 0.65, "direction": direction}
            slot.close_trade = lambda *a, **k: closed.append(name)
            return slot

        control.position_classes = [
            _slot("flip_long", 1, 5.0, owner_tag="flip_predict_aud"),
            _slot("flip_short", -1, 5.0, owner_tag="flip_predict_aud"),
        ]
        control.close_hedge_positions()
        self.assertEqual(
            closed, [], "タグ付きの両建ては解消されてはいけない"
        )


class CloseTradeFailureTest(unittest.TestCase):
    """決済APIが失敗したときに、実建玉と life の食い違いを起こさないこと。"""

    def _position(self, close_error, detail):
        position = classPosition.order_information("slot", False)
        position.t_id = 12345
        position.t_pl_pips = 0.0
        position.life = True
        position.oa = types.SimpleNamespace(
            TradeClose_exe=lambda tid, u: {"error": close_error},
            TradeDetails_exe=lambda tid: detail,
        )
        position.send_line = lambda *a, **k: None
        position.after_close_trade_function = lambda: None
        return position

    def _detail(self, state):
        return {"error": 0, "data": {"trade": {"state": state}}}

    def test_failed_close_keeps_life_when_trade_is_still_open(self):
        # 決済が通っていないなら、監視対象から外してはいけない。
        position = self._position(-1, self._detail("OPEN"))
        position.close_trade(None)
        self.assertTrue(
            position.life, "残存建玉の life を下ろすと誰も決済しなくなる"
        )

    def test_failed_close_drops_life_when_trade_is_already_closed(self):
        # 決済は成立していて応答だけ失われた場合、スロットは解放する。
        position = self._position(-1, self._detail("CLOSED"))
        position.close_trade(None)
        self.assertFalse(position.life)

    def test_unverifiable_close_keeps_life(self):
        # 実在を確認できないときは、残っている前提で維持する（安全側）。
        position = self._position(-1, {"error": 1, "data": {}})
        position.close_trade(None)
        self.assertTrue(position.life)

    def test_successful_close_drops_life(self):
        position = self._position(0, self._detail("CLOSED"))
        position.close_trade(None)
        self.assertFalse(position.life)


class CancelScopeTest(unittest.TestCase):
    """起動時キャンセルが、担当通貨の外へ及ばないこと。"""

    def _oanda(self, orders):
        import classOanda

        oa = classOanda.Oanda.__new__(classOanda.Oanda)
        oa.OrdersPending_exe = lambda: {
            "data": pd.DataFrame(orders),
            "error": 0,
        }
        oa.cancelled = []
        oa.OrderCancel_exe = lambda oid: oa.cancelled.append(oid)
        return oa

    def _orders(self):
        return [
            {"id": "1", "type": "LIMIT", "instrument": "AUD_USD"},
            {"id": "2", "type": "STOP", "instrument": "EUR_USD"},
            {"id": "3", "type": "LIMIT", "instrument": "EUR_USD"},
            # 建玉に付いた利確・損切りは、そもそも対象外。
            {"id": "4", "type": "TAKE_PROFIT", "instrument": "AUD_USD"},
            {"id": "5", "type": "STOP_LOSS", "instrument": "AUD_USD"},
        ]

    def test_pair_given_cancels_only_that_pair(self):
        oa = self._oanda(self._orders())
        oa.OrderCancel_All_exe("AUD_USD")
        self.assertEqual(
            oa.cancelled, ["1"], "他通貨の待機注文を消してはいけない"
        )

    def test_no_pair_keeps_the_account_wide_behaviour(self):
        oa = self._oanda(self._orders())
        oa.OrderCancel_All_exe()
        # 従来どおり、口座全体の新規注文が対象（TP/SLは除く）。
        self.assertEqual(oa.cancelled, ["1", "2", "3"])

    def test_missing_instrument_column_cancels_nothing_when_scoped(self):
        # 絞れないときに全消しへ倒すと事故になるので、何もしない。
        oa = self._oanda([{"id": "1", "type": "LIMIT"}])
        oa.OrderCancel_All_exe("AUD_USD")
        self.assertEqual(oa.cancelled, [])


class OneAtATimeTest(unittest.TestCase):
    """flip は同時に一つだけ（検証と同じ前提）。"""

    def _control(self, slots):
        return types.SimpleNamespace(position_classes=slots)

    def _slot(self, life=True, origin=""):
        return types.SimpleNamespace(life=life, origin=origin)

    def test_no_flip_slot_allows_a_new_signal(self):
        control = self._control([self._slot(life=False, origin="flip")])
        self.assertFalse(fFlipOrder.has_active_flip(control))

    def test_live_flip_slot_blocks_a_new_signal(self):
        control = self._control([self._slot(life=True, origin="flip")])
        self.assertTrue(fFlipOrder.has_active_flip(control))

    def test_other_origins_do_not_block_flip(self):
        # 旧戦略や手動の建玉は flip の枠を塞がない。
        control = self._control(
            [self._slot(life=True, origin=""), self._slot(life=True, origin="x")]
        )
        self.assertFalse(fFlipOrder.has_active_flip(control))


class OriginRestoreTest(unittest.TestCase):
    """再起動後、OANDA のタグから出自が戻ること。"""

    def _trade(self, tag=None):
        trade = {
            "id": "9001",
            "instrument": "AUD_USD",
            "price": "0.65000",
            "currentUnits": "100",
            "initialUnits": "100",
            "unrealizedPL": "0",
            "state": "OPEN",
            "openTime": "2026-08-27T00:00:00.000000000Z",
        }
        if tag is not None:
            trade["clientExtensions"] = {"tag": tag}
        return trade

    def test_flip_tag_restores_origin_and_owner_tag(self):
        position = classPosition.order_information("slot", False)
        position.catch_exist_position(
            "既存0", 2, 5, self._trade(tag="flip_predict_aud")
        )
        self.assertEqual(position.origin, fFlipOrder.ORIGIN)
        self.assertEqual(position.owner_tag, "flip_predict_aud")

    def test_unknown_tag_leaves_origin_empty(self):
        position = classPosition.order_information("slot", False)
        position.catch_exist_position(
            "既存0", 2, 5, self._trade(tag="managed_profit_lock")
        )
        self.assertEqual(position.origin, "")
        self.assertEqual(position.owner_tag, "")

    def test_no_tag_leaves_origin_empty(self):
        position = classPosition.order_information("slot", False)
        position.catch_exist_position("既存0", 2, 5, self._trade())
        self.assertEqual(position.origin, "")

    def test_restored_flip_position_blocks_a_new_signal(self):
        # 再起動直後でも「1つだけ」が効くこと（この経路が本題）。
        position = classPosition.order_information("slot", False)
        position.catch_exist_position(
            "既存0", 2, 5, self._trade(tag="flip_predict_aud")
        )
        control = types.SimpleNamespace(position_classes=[position])
        self.assertTrue(fFlipOrder.has_active_flip(control))


class WatchCausalityTest(unittest.TestCase):
    """見張りが、注文前の足や形成中の足でタッチと判定しないこと。"""

    def _position(self, line_price=150.0, peak_direction=1, registered=None):
        position = types.SimpleNamespace()
        position.pair = "USD_JPY"
        position.plan_json = {
            "flip_line_price": line_price,
            "flip_peak_direction": peak_direction,
            "flip_spread_pips": 0.8,
        }
        position.order_register_time = registered
        position.waiting_order = True
        position.watching_for_position_done = False
        position.o_state = "Watching"
        position.placed = []
        position.make_order = lambda: (
            position.placed.append("order") or {"order_id": 1}
        )
        return position

    def _frame(self, rows):
        """時刻降順（共有フレームと同じ並び）で S5 を作る。"""
        frame = pd.DataFrame(rows)
        return types.SimpleNamespace(
            s5_completed_df_r=frame.iloc[::-1].reset_index(drop=True)
        )

    def test_touch_before_the_order_is_ignored(self):
        # 注文登録より前に既にラインへ触れていた足で発注してはいけない。
        registered = datetime.datetime(2025, 1, 6, 9, 0, 0)
        position = self._position(registered=registered)
        before = registered - datetime.timedelta(seconds=10)
        frame = self._frame(
            [
                {
                    "time_jp": before,
                    "open": 149.9,
                    "high": 150.5,  # ラインを大きく超えている
                    "low": 149.8,
                    "close": 150.4,
                    "complete": True,
                }
            ]
        )
        fFlipWatch.watch(position, frame)
        self.assertEqual(position.placed, [])
        self.assertEqual(
            position.flip_watch_state["phase"], "PENDING_TOUCH"
        )

    def test_touch_after_the_order_still_fires(self):
        registered = datetime.datetime(2025, 1, 6, 9, 0, 0)
        position = self._position(registered=registered)
        after = registered + datetime.timedelta(seconds=5)
        frame = self._frame(
            [
                {
                    "time_jp": after,
                    "open": 149.9,
                    "high": 150.5,
                    "low": 149.8,
                    "close": 150.4,
                    "complete": True,
                }
            ]
        )
        fFlipWatch.watch(position, frame)
        self.assertEqual(position.placed, ["order"])
        self.assertFalse(position.waiting_order)

    def test_forming_bar_is_not_used_for_the_touch(self):
        # 形成中の足は高値がまだ動くので、確定するまで使わない。
        registered = datetime.datetime(2025, 1, 6, 9, 0, 0)
        position = self._position(registered=registered)
        after = registered + datetime.timedelta(seconds=5)
        frame = self._frame(
            [
                {
                    "time_jp": after,
                    "open": 149.9,
                    "high": 150.5,
                    "low": 149.8,
                    "close": 150.4,
                    "complete": False,
                }
            ]
        )
        fFlipWatch.watch(position, frame)
        self.assertEqual(position.placed, [])

    def test_frames_without_a_completion_flag_are_rejected(self):
        # 完成を証明できないフレームでは、誤発注せず見送る。
        registered = datetime.datetime(2025, 1, 6, 9, 0, 0)
        position = self._position(registered=registered)
        after = registered + datetime.timedelta(seconds=5)
        frame = self._frame(
            [
                {
                    "time_jp": after,
                    "open": 149.9,
                    "high": 150.5,
                    "low": 149.8,
                    "close": 150.4,
                }
            ]
        )
        fFlipWatch.watch(position, frame)
        self.assertEqual(position.placed, [])
        self.assertTrue(position.waiting_order)

    def test_missing_watch_start_is_rejected(self):
        position = self._position(registered=None)
        frame = self._frame(
            [
                {
                    "time_jp": datetime.datetime(2025, 1, 6, 9, 0, 5),
                    "open": 149.9,
                    "high": 150.5,
                    "low": 149.8,
                    "close": 150.4,
                    "complete": True,
                }
            ]
        )
        fFlipWatch.watch(position, frame)
        self.assertEqual(position.placed, [])
        self.assertTrue(position.waiting_order)

    def test_utc_decision_time_is_compared_as_jst(self):
        position = self._position(registered=None)
        position.plan_json["decision_time"] = "2025-01-06T00:00:00+00:00"
        before_decision_jst = datetime.datetime(2025, 1, 6, 8, 59, 55)
        frame = self._frame(
            [
                {
                    "time_jp": before_decision_jst,
                    "open": 149.9,
                    "high": 150.5,
                    "low": 149.8,
                    "close": 150.4,
                    "complete": True,
                }
            ]
        )
        fFlipWatch.watch(position, frame)
        self.assertEqual(position.placed, [])

    def test_later_of_decision_and_registration_is_used(self):
        registered = datetime.datetime(2025, 1, 6, 8, 59, 55)
        position = self._position(registered=registered)
        position.plan_json["decision_time"] = "2025-01-06T00:00:00+00:00"
        frame = self._frame(
            [
                {
                    "time_jp": registered,
                    "open": 149.9,
                    "high": 150.5,
                    "low": 149.8,
                    "close": 150.4,
                    "complete": True,
                }
            ]
        )
        fFlipWatch.watch(position, frame)
        self.assertEqual(position.placed, [])

if __name__ == "__main__":
    unittest.main()
