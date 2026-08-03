import datetime
from datetime import timedelta

import classOanda
import tokens as tk
import send_notice as notice
import fGeneric as gene
import classPosition as classPosition  # とりあえずの関数集
from classOpposingPositionPolicy import OpposingPositionPolicy
import archive.classPositionForTest as testClassPosition

from collections import deque  # 最大10個の情報を持つためのもの。
import copy



class position_control:
    """
    ポジションクラスをコントロースするためのもの
    """
    # 常に最新のデータを取得してクラス変数に入れておく（毎回の取得はしないように工夫する。（してもいい気もするけど））


    # 履歴ファイル
    def __init__(self, is_live, pair="USD_JPY"):
        self.result_class_arr = deque(maxlen=10)
        self.is_live = is_live
        self.pair = pair
        self.p = gene.currency_pair(self.pair)

        # 変数の宣言
        self.u = self.p.round_keta
        self.position_classes = []
        self.count_true = 0
        self.oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, tk.environmentl)
        self.oa2 = classOanda.Oanda(tk.accountIDl2, tk.access_tokenl, tk.environmentl)

        self.peaks_class = ""  # クラスアップデートの時に利用する（ポジションクラスに引数として渡すため）

        # 最大所持個数の設定
        self.max_position_num = 15  # 最大でも10個のポジションしかもてないようにする
        self.middle_priority_num = 8  # ミドルプライオリティ(max_position_numのうち）
        self.high_priority_num = 1  # ハイプライオリティのもの（max_position_numのうち）

        self.high_i_to = self.max_position_num
        self.high_i_from = self.high_i_to - self.high_priority_num  # ハイプライオリティスロット(1つ限)の、添え字（最大5スロットの場合、添え字的には4番目スロット）
        self.mid_i_to = self.high_i_from  # python配列のTO指定は「未満」なので、ー１が不要。（以下の場合はマイナスが必要）
        self.mid_i_from = self.mid_i_to - self.middle_priority_num
        self.normal_i_to = self.mid_i_from
        self.normal_i_from = 0

        self.normal_priority_num = self.max_position_num - self.high_priority_num

        # 処理
        for i in range(self.max_position_num):
            # 複数のクラスを動的に生成する。クラス名は「C＋通し番号」とする。
            # クラス名を確定し、クラスを生成する。
            new_name = "c" + str(i)
            self.position_classes.append(classPosition.order_information(new_name, is_live))  # 順思想のオーダーを入れるクラス
        self.print_classes_and_count()

    def print_classes_and_count(self):
        self.count_true = sum(1 for d in self.position_classes if hasattr(d, "life") and d.life)
        i = 0
        print(" 現在のクラスの状況(True:", self.count_true, ")")
        for i, item in enumerate(self.position_classes):
            if self.high_i_from <= i < self.high_i_to:
                comment = "h"
            elif self.mid_i_from <= i < self.mid_i_to:
                comment = "m"
            else:
                comment = "n"
            print(" ", i, "OaMode:", item.oa_mode, "[", comment, "], Pno:", item.t_id, ",name:", item.name, ",life:", item.life)

        # テスト
        # allowed_position_slot = self.position_classes[self.mid_i_from:self.mid_i_to]
        # for i, item in enumerate(allowed_position_slot):
        #     print(" ", i, "OaMode:", item.oa_mode, "Pno:", item.t_id, ",name:", item.name, ",life:", item.life)

    def filter_similar_order_classes(self, order_classes, threshold_pips=3):
        p = self.p
        candidates = []
        for order_class in order_classes:
            plan = getattr(order_class, "exe_order_plan", None) or {}
            direction = plan.get("direction")
            target_price = plan.get("target_price")
            if direction is None or target_price is None:
                candidates.append({
                    "order_class": order_class,
                    "direction": direction,
                    "target_price": target_price,
                    "distance_pips": 0,
                    "can_compare": False,
                })
                continue

            current_price = getattr(order_class, "current_price", target_price)
            distance_pips = abs(p.price_to_pips(float(current_price) - float(target_price)))
            candidates.append({
                "order_class": order_class,
                "direction": direction,
                "target_price": target_price,
                "distance_pips": distance_pips,
                "can_compare": True,
            })

        selected = []
        for candidate in sorted(candidates, key=lambda x: x["distance_pips"]):
            order_class = candidate["order_class"]
            plan = getattr(order_class, "exe_order_plan", None) or {}
            if not candidate["can_compare"]:
                selected.append(candidate)
                continue

            duplicate_new_order = False
            for selected_candidate in selected:
                if not selected_candidate["can_compare"]:
                    continue
                if int(selected_candidate["direction"]) != int(candidate["direction"]):
                    continue
                gap_pips = abs(p.price_to_pips(float(candidate["target_price"]) - float(selected_candidate["target_price"])))
                if gap_pips <= threshold_pips:
                    print(
                        "Skip similar new order:",
                        plan.get("name"),
                        "target",
                        candidate["target_price"],
                        "near",
                        selected_candidate["target_price"],
                        "gap_pips",
                        round(gap_pips, 1),
                    )
                    duplicate_new_order = True
                    break
            if duplicate_new_order:
                continue

            active_result = self.find_similar_active_order(
                candidate["direction"],
                candidate["target_price"],
                threshold_pips,
            )
            if active_result["is_exist"]:
                print(
                    "Skip similar active order:",
                    plan.get("name"),
                    "target",
                    candidate["target_price"],
                    "active",
                    active_result.get("name"),
                    "active_target",
                    active_result.get("target_price"),
                    "gap_pips",
                    round(active_result.get("gap_pips", 0), 1),
                )
                continue

            selected.append(candidate)

        return [candidate["order_class"] for candidate in selected]

    def order_class_add(self, order_classes):
        """
        調査結果を受け取り、他のオーダーを比較し、オーダーを追加するかを判定する
        """
        # ■オーダーのプライオリティの関係
        # 渡されたオーダーの中で、最大のプライオリティのものと、そのプライオリティを算出
        # max_dict = max(order_dic_list, key=lambda d: d["priority"], default=None)
        # max_dict = max(order_dic_list, key=lambda d: d.get("priority", float("-inf")))
        # order_max_priority = max_dict['priority']
        order_classes = self.process_predict_reversal_count2_controls(
            order_classes
        )
        if len(order_classes) == 0:
            print("No executable order classes after count2 control.")
            return 0
        order_classes = self.filter_breakouts_near_pending_predict_reversals(
            order_classes,
            threshold_pips=3,
        )
        if len(order_classes) == 0:
            print("No order classes after predict-reversal priority filter.")
            return 0

        # Run this before same-direction duplicate removal.  A refreshed
        # predict signal may itself be a duplicate, but it must still remove a
        # stale opposite breakout near that resistance line.
        order_classes = self.resolve_predict_reversal_pending_conflicts(
            order_classes,
            threshold_pips=3,
        )
        if len(order_classes) == 0:
            print("No order classes after pending-order conflict filter.")
            return 0
        order_classes = self.filter_similar_order_classes(order_classes, threshold_pips=3)
        if len(order_classes) == 0:
            print("No order classes after similar-order filter.")
            return 0
        order_classes = self.apply_opposing_position_policy(order_classes)
        if len(order_classes) == 0:
            print("No order classes after opposing-position policy.")
            return 0

        max_instance = max(order_classes, key=lambda x: x.exe_order_plan["priority"])
        order_max_priority = max_instance.exe_order_plan['priority']
        if order_max_priority >=100:
            order_priority_class = "high"
            i_from = self.high_i_from
            i_to = self.high_i_to
        elif order_max_priority >= 10:
            order_priority_class = "mid"
            i_from = self.mid_i_from
            i_to = self.mid_i_to
        else:
            order_priority_class = "normal"
            i_from = self.normal_i_from
            i_to = self.normal_i_to
        allowed_position_slot = self.position_classes[i_from:i_to]  # もらったオーダーの優先度で、許可されたスロット(positionList)

        for i, order_class in enumerate(allowed_position_slot):
            print(" Allowed　", i, "OaMode:", order_class.oa_mode, ",name:", order_class.name, ",life:", order_class.life)
            i = i + 1

        # 現在のクラスで、生きている物のみ抽出
        alive_classes = [c for c in allowed_position_slot if hasattr(c, "life") and c.life]
        if len(alive_classes) == 0:
            print(" プログラム上既存のオーダーは存在しないため、オーダー発行へ")
            pass
        elif len(alive_classes) == len(allowed_position_slot):
            notice.line_send("許容スロットがいっぱい（オーダー発行せず)", len(alive_classes), len(allowed_position_slot))
            self.print_classes_and_count()
            return 0
        elif len(order_classes) + len(alive_classes) > len(allowed_position_slot):
            notice.line_send("オーダー入れるとオーバーフロー（オーダー発行せず)", len(order_classes), len(alive_classes), len(allowed_position_slot))
            self.print_classes_and_count()
            return 0
        else:
            # 生きているインスタンスの最高値と、指定のプライオリティより高いものを算出
            max_instance = max(alive_classes, key=lambda c: getattr(c, "priority", float("-inf")))
            over_n_classes = [c for c in alive_classes if hasattr(c, "priority") and c.priority > order_max_priority]
            same_n_classes = [c for c in alive_classes if hasattr(c, "priority") and c.priority == order_max_priority]

        # ■現在のクラスの状況の確認
        print("現在のクラスの状況を確認 (classPositionControl)")
        self.print_classes_and_count()
        # 通常のオーダーの場合
        # if self.count_true >= self.normal_priority_num:
        #     # 10個以上オーダーがある場合はオーダーしない。
        #     print("★★既に10個以上オーダーがあるため、オーダー発行しない")
        #     return 0
        # elif self.count_true + len(order_classes) > self.max_position_num:  # ２はテキトーな数字。
        #     # 新規のオーダー合わせて13個以上になる場合もオーダーしない（新規オーダーがエラーで複数個出てる可能性のため）
        #     print("★★既存の物＋新規の合わせて12個以上になるため、オーダー発行しない(新規オーダー数:", len(order_classes))
        #     return 0

        # クラスに余りがある場合、その中で添え字が一番若いオーダーに上書き、または、追加をする
        line_send = ""
        for order_i, order_class in enumerate(order_classes):
            for class_index, position_slot in enumerate(allowed_position_slot):
                # 指定ランクの空きスロットを巡回する
                if position_slot.life:
                    # Trueの所には上書きしない
                    continue
                if class_index == self.high_i_from:
                    # ハイクラス用の添え字の場所には、入れない
                    continue

                # Falseのとこで実行する
                res_dic = position_slot.order_plan_registration(order_class)
                lc_change_str = ""
                for i, item in enumerate(order_class.lc_change):
                    if i == 2:
                        break
                    lc_change_str = lc_change_str + ",(" + str(item['trigger']) + "-" + str(item['ensure']) + ")"

                if res_dic['order_id'] == 0:
                    print("オーダー失敗している（大量オーダー等）")
                    line_send = line_send + "オーダー失敗(" + str(order_i) + ")" + "\n"
                else:
                    # ■オーダーが成功している場合
                    if res_dic['order_id'] == -1:
                        # ウォッチオーダー
                        print("オーダー通知 idが-1のもの")
                        # new
                        line_send = line_send + position_slot.for_line_send_order_info + "[システム]classNo:" + str(class_index) + "\n"
                        break
                    else:
                        # オーダーの生成完了をLINE通知するための、コメントを生成する
                        # print("オーダー通知", res_dic['order_name'])
                        # new
                        line_send = line_send + position_slot.for_line_send_order_info + "[システム]classNo:" + str(class_index) + "\n"
                        break

        # ポジションスロットを巡回し、リンケージオーダーがある場合、互いにスロットを登録する
        for class_index, position_slot in enumerate(allowed_position_slot):
            # 指定ランクの空きスロットを巡回する
            if not position_slot.life or len(position_slot.linkage_class_slots) >= 1:
                # Trueの所には上書きしない
                print("    ポジションスロットを入れ替えない(登録済?)", position_slot.life, position_slot.name, len(position_slot.linkage_class_slots))
                continue

            # スロットルの中身を確認（オーダークラスに、リンケージオーダーの名前が配列で格納されている）
            if len(position_slot.linkage_order_classes) == 0:
                pass
                print("     オーダーレジストレーション リンケージオーダーなし", position_slot.name)
            else:
                print("     オーダーレジストレーション　リンケージオーダーあり", position_slot.name, "リンク先[0]",
                      position_slot.linkage_order_classes[0].name)

                # とりあえず、、代表の一つの「名前」を取得（名前はユニーク）
                target_name = position_slot.linkage_order_classes[0].name
                for linkage_to in allowed_position_slot:
                    # 同じ名前を持つ、ポジションクラスを探す。
                    if linkage_to.name == target_name:
                        print("      ⇒相手発見 自分のlinakageに登録する", linkage_to.name, target_name)
                        position_slot.linkage_class_slots.append(linkage_to)
                        print(" 複製チェック！！！！")
                        print("スロットのID", id(position_slot))
                        print(" リンク先", id(linkage_to))
                        print("格納後のやつ", id(position_slot.linkage_class_slots[0]))
                        break

        return line_send

    def process_predict_reversal_count2_controls(self, order_classes):
        """Expire older pending predicts even when a new count2 has no order."""
        executable = []
        for order_class in order_classes:
            plan = getattr(order_class, "exe_order_plan", None) or {}
            if (
                plan.get("line_order_mode")
                != "predict_reversal_count2_control"
            ):
                executable.append(order_class)
                continue
            if not self.is_live:
                continue

            if not self._resolve_pending_orders_for_predict(
                plan,
                threshold_pips=3,
                resolve_breakouts=False,
            ):
                plan["pending_conflict_action"] = (
                    "count2_expiry_failed_closed"
                )
                print(
                    "Count2 control could not expire previous predict:",
                    plan.get("predict_signal_id"),
                    plan.get("pending_conflict_reason"),
                )
                continue
            plan["pending_conflict_action"] = (
                "count2_expiry_processed"
            )
        return executable

    def filter_breakouts_near_pending_predict_reversals(
        self,
        order_classes,
        threshold_pips=3,
    ):
        """Give a pending predict reversal priority over an opposite breakout."""
        if not self.is_live:
            return order_classes

        new_predict_plans = []
        for order_class in order_classes:
            plan = getattr(order_class, "exe_order_plan", None) or {}
            if plan.get("line_order_mode") == "predict_reversal":
                new_predict_plans.append(plan)

        allowed = []
        for order_class in order_classes:
            plan = getattr(order_class, "exe_order_plan", None) or {}
            if not (
                plan.get("source") == "line"
                and plan.get("line_entry_type") == "breakout"
            ):
                allowed.append(order_class)
                continue

            try:
                breakout_direction = int(plan["direction"])
                breakout_target = float(plan["target_price"])
            except (KeyError, TypeError, ValueError):
                allowed.append(order_class)
                continue

            blocked = False
            for predict_plan in new_predict_plans:
                try:
                    predict_direction = int(predict_plan["direction"])
                    predict_target = float(predict_plan["target_price"])
                except (KeyError, TypeError, ValueError):
                    continue
                gap_pips = abs(
                    self.p.price_to_pips(breakout_target - predict_target)
                )
                if (
                    breakout_direction == -predict_direction
                    and gap_pips <= threshold_pips
                ):
                    plan["predict_pending_guard_action"] = "block_breakout"
                    plan["predict_pending_guard_reason"] = (
                        "new_predict_reversal_same_cycle"
                    )
                    blocked = True
                    break
            if blocked:
                continue

            for item in self.position_classes:
                if not getattr(item, "life", False):
                    continue
                if getattr(item, "o_state", None) != "PENDING":
                    continue
                existing_plan = getattr(item, "plan_json", None) or {}
                if existing_plan.get("line_order_mode") != "predict_reversal":
                    continue
                try:
                    predict_direction = int(existing_plan["direction"])
                    predict_target = float(existing_plan["target_price"])
                except (KeyError, TypeError, ValueError):
                    continue
                if breakout_direction != -predict_direction:
                    continue
                gap_pips = abs(
                    self.p.price_to_pips(breakout_target - predict_target)
                )
                if gap_pips > threshold_pips:
                    continue

                order_api = getattr(item, "oa", None)
                order_id = getattr(item, "o_id", None)
                if order_api is None or order_id in (None, 0, ""):
                    plan["predict_pending_guard_action"] = "block_breakout"
                    plan["predict_pending_guard_reason"] = (
                        "pending_predict_missing_order_reference"
                    )
                    blocked = True
                    break

                details = order_api.OrderDetails_exe(order_id)
                if details.get("error") != 0:
                    plan["predict_pending_guard_action"] = "block_breakout"
                    plan["predict_pending_guard_reason"] = (
                        "pending_predict_status_fetch_failed"
                    )
                    plan["predict_pending_guard_order_id"] = order_id
                    blocked = True
                    break
                state = (
                    details.get("data", {})
                    .get("order", {})
                    .get("state")
                )
                if state == "PENDING":
                    plan["predict_pending_guard_action"] = "block_breakout"
                    plan["predict_pending_guard_reason"] = (
                        "pending_predict_reversal_has_priority"
                    )
                    plan["predict_pending_guard_order_id"] = order_id
                    blocked = True
                    break
                if state == "CANCELLED":
                    item.o_state = state
                    item.life_set(False)
                    continue
                if state == "FILLED":
                    # It is no longer a pending-order conflict.  The existing
                    # open-trade policy decides whether the breakout may reverse it.
                    # Keep the local state PENDING here: classPosition's next
                    # regular update must observe PENDING -> FILLED itself so
                    # fill notifications and linked-order cancellation still run.
                    continue

                plan["predict_pending_guard_action"] = "block_breakout"
                plan["predict_pending_guard_reason"] = (
                    "pending_predict_unknown_state:" + str(state)
                )
                plan["predict_pending_guard_order_id"] = order_id
                blocked = True
                break

            if blocked:
                print(
                    "Block breakout by pending predict reversal:",
                    plan.get("name"),
                    plan.get("target_price"),
                    plan.get("predict_pending_guard_reason"),
                )
                continue
            allowed.append(order_class)

        return allowed

    def resolve_predict_reversal_pending_conflicts(
        self,
        order_classes,
        threshold_pips=3,
    ):
        """Resolve stale pending orders before a predict reversal.

        A new count2 expires every still-pending predict order from an older
        count2.  It also cancels an opposite breakout near the new resistance
        target.  If server state cannot be confirmed or cancellation fails,
        the new reversal is blocked instead of allowing conflicting orders.
        """
        if not self.is_live:
            return order_classes

        allowed = []
        for order_class in order_classes:
            plan = getattr(order_class, "exe_order_plan", None) or {}
            if plan.get("line_order_mode") != "predict_reversal":
                allowed.append(order_class)
                continue

            if self._resolve_pending_orders_for_predict(
                plan,
                threshold_pips,
            ):
                if plan.get("pending_same_signal_order_exists"):
                    plan["pending_conflict_action"] = (
                        "keep_existing_same_count2_predict"
                    )
                    continue
                allowed.append(order_class)
                continue

            plan["pending_conflict_action"] = "block_predict_reversal"
            print(
                "Block predict reversal by pending-order conflict:",
                plan.get("name"),
                plan.get("target_price"),
            )
        return allowed

    @staticmethod
    def _predict_signal_identity(plan):
        signal_id = plan.get("predict_signal_id")
        if signal_id not in (None, ""):
            return str(signal_id)
        try:
            direction = int(plan["latest_peak_dir"])
        except (KeyError, TypeError, ValueError):
            return None
        signal_time = plan.get("latest_peak_time")
        if signal_time in (None, ""):
            return None
        return str(direction) + ":" + str(signal_time)

    def _resolve_pending_orders_for_predict(
        self,
        predict_plan,
        threshold_pips,
        resolve_breakouts=True,
    ):
        predict_signal_id = self._predict_signal_identity(predict_plan)
        if predict_signal_id is None:
            predict_plan["pending_conflict_reason"] = (
                "predict_signal_identity_missing"
            )
            return False
        predict_direction = None
        predict_target = None
        if resolve_breakouts:
            try:
                predict_direction = int(predict_plan["direction"])
                predict_target = float(predict_plan["target_price"])
            except (KeyError, TypeError, ValueError):
                return False

        conflicts = []
        same_signal_pending_refs = []
        same_signal_order_exists = False
        same_signal_filled_exists = False
        for item in self.position_classes:
            if not getattr(item, "life", False):
                continue

            existing_plan = getattr(item, "plan_json", None) or {}
            if existing_plan.get("line_order_mode") == "predict_reversal":
                existing_signal_id = self._predict_signal_identity(
                    existing_plan
                )
                if existing_signal_id == predict_signal_id:
                    local_state = getattr(item, "o_state", None)
                    if local_state == "CANCELLED":
                        item.life_set(False)
                        continue
                    if (
                        local_state == "FILLED"
                        or getattr(item, "t_state", None) == "OPEN"
                    ):
                        same_signal_filled_exists = True
                        continue
                    if local_state not in (None, "", "PENDING"):
                        predict_plan["pending_conflict_reason"] = (
                            "same_signal_predict_unknown_local_state:"
                            + str(local_state)
                        )
                        return False
                    order_api = getattr(item, "oa", None)
                    order_id = getattr(item, "o_id", None)
                    if order_api is None or order_id in (None, 0, ""):
                        predict_plan["pending_conflict_reason"] = (
                            "same_signal_predict_missing_order_reference"
                        )
                        return False
                    same_signal_pending_refs.append(
                        (item, order_api, order_id)
                    )
                    continue

                local_state = getattr(item, "o_state", None)
                order_id = getattr(item, "o_id", None)
                if local_state == "CANCELLED":
                    item.life_set(False)
                    continue
                if local_state not in (None, "", "PENDING"):
                    predict_plan["pending_conflict_reason"] = (
                        "previous_predict_no_longer_cancellable:"
                        + str(local_state)
                    )
                    predict_plan["pending_conflict_failed_order_id"] = (
                        order_id
                    )
                    return False

                order_api = getattr(item, "oa", None)
                if order_api is None or order_id in (None, 0, ""):
                    predict_plan["pending_conflict_reason"] = (
                        "previous_predict_missing_order_reference"
                    )
                    return False
                conflicts.append(
                    (item, order_api, order_id, "previous_predict")
                )
                continue

            if not resolve_breakouts:
                continue
            if getattr(item, "o_state", None) != "PENDING":
                continue
            if existing_plan.get("source") != "line":
                continue
            if existing_plan.get("line_entry_type") != "breakout":
                continue
            try:
                existing_direction = int(existing_plan["direction"])
                existing_target = float(existing_plan["target_price"])
            except (KeyError, TypeError, ValueError):
                continue
            if existing_direction != -predict_direction:
                continue

            gap_pips = abs(
                self.p.price_to_pips(predict_target - existing_target)
            )
            if gap_pips > threshold_pips:
                continue

            order_api = getattr(item, "oa", None)
            order_id = getattr(item, "o_id", None)
            if order_api is None or order_id in (None, 0, ""):
                predict_plan["pending_conflict_reason"] = (
                    "pending_breakout_missing_order_reference"
                )
                return False

            conflicts.append((item, order_api, order_id, "pending_breakout"))

        # Resolve same-count2 duplicates first, but do not cancel yet.  One
        # still-PENDING order is canonical; extras are cancelled.  If one has
        # filled, every remaining PENDING duplicate is cancelled and the new
        # order is suppressed.
        same_signal_pending = []
        for item, order_api, order_id in same_signal_pending_refs:
            details = order_api.OrderDetails_exe(order_id)
            if details.get("error") != 0:
                predict_plan["pending_conflict_reason"] = (
                    "same_signal_predict_status_fetch_failed"
                )
                predict_plan["pending_conflict_failed_order_id"] = order_id
                return False
            state = (
                details.get("data", {})
                .get("order", {})
                .get("state")
            )
            if state == "PENDING":
                same_signal_pending.append((item, order_api, order_id))
                continue
            if state == "CANCELLED":
                item.o_state = state
                item.life_set(False)
                continue
            if state == "FILLED":
                # Preserve local PENDING so the regular update owns the
                # PENDING -> FILLED transition and linkage cancellation.
                same_signal_filled_exists = True
                continue
            predict_plan["pending_conflict_reason"] = (
                "same_signal_predict_unknown_server_state:" + str(state)
            )
            predict_plan["pending_conflict_failed_order_id"] = order_id
            return False

        cancellable = []
        if same_signal_filled_exists:
            same_signal_order_exists = True
            duplicate_same_signal = same_signal_pending
        elif same_signal_pending:
            same_signal_order_exists = True
            duplicate_same_signal = same_signal_pending[1:]
        else:
            duplicate_same_signal = []
        cancellable.extend(
            (
                item,
                order_api,
                order_id,
                "duplicate_same_signal_predict",
            )
            for item, order_api, order_id in duplicate_same_signal
        )

        # Confirm every other server state before cancelling anything.  This avoids
        # cancelling the first order and only then discovering that a second
        # conflict is already filled or cannot be inspected.
        for item, order_api, order_id, conflict_kind in conflicts:
            details = order_api.OrderDetails_exe(order_id)
            if details.get("error") != 0:
                predict_plan["pending_conflict_reason"] = (
                    conflict_kind + "_status_fetch_failed"
                )
                predict_plan["pending_conflict_failed_order_id"] = order_id
                return False
            state = (
                details.get("data", {})
                .get("order", {})
                .get("state")
            )
            if state == "PENDING":
                cancellable.append(
                    (item, order_api, order_id, conflict_kind)
                )
                continue

            if state == "CANCELLED":
                item.o_state = state
                item.life_set(False)
                continue

            # FILLED or an unknown server state: do not place an opposite order.
            predict_plan["pending_conflict_reason"] = (
                conflict_kind + "_no_longer_cancellable:" + str(state)
            )
            predict_plan["pending_conflict_failed_order_id"] = order_id
            return False

        cancelled_ids = []
        cancelled_predict_ids = []
        cancelled_breakout_ids = []
        cancelled_same_signal_ids = []
        for item, order_api, order_id, conflict_kind in cancellable:
            cancel_result = order_api.OrderCancel_exe(order_id)
            if cancel_result.get("error") != 0:
                predict_plan["pending_conflict_reason"] = (
                    conflict_kind + "_cancel_failed"
                )
                predict_plan["pending_conflict_failed_order_id"] = order_id
                predict_plan["pending_conflict_cancelled_order_ids"] = list(
                    cancelled_ids
                )
                return False
            item.o_state = "CANCELLED"
            item.life_set(False)
            cancelled_ids.append(order_id)
            if conflict_kind == "previous_predict":
                cancelled_predict_ids.append(order_id)
            elif conflict_kind == "pending_breakout":
                cancelled_breakout_ids.append(order_id)
            else:
                cancelled_same_signal_ids.append(order_id)

        if cancelled_ids:
            cancelled_groups = sum(
                bool(group)
                for group in (
                    cancelled_predict_ids,
                    cancelled_breakout_ids,
                    cancelled_same_signal_ids,
                )
            )
            if cancelled_groups > 1:
                action = "cancel_multiple_predict_pending_conflicts"
            elif cancelled_predict_ids:
                action = "replace_previous_count2_predict"
            elif cancelled_same_signal_ids:
                action = "dedupe_same_count2_predict"
            else:
                action = "cancel_opposite_pending_breakout"
            predict_plan["pending_conflict_action"] = action
            predict_plan["pending_conflict_cleanup_action"] = action
            predict_plan["pending_conflict_cancelled_order_ids"] = list(
                cancelled_ids
            )
            predict_plan["pending_conflict_replaced_predict_order_ids"] = (
                list(cancelled_predict_ids)
            )
            predict_plan["pending_conflict_cancelled_breakout_order_ids"] = (
                list(cancelled_breakout_ids)
            )
            predict_plan[
                "pending_conflict_cancelled_same_signal_order_ids"
            ] = list(cancelled_same_signal_ids)
            # Keep the original scalar field for existing logs/consumers.
            predict_plan["pending_conflict_cancelled_order_id"] = (
                cancelled_ids[0]
            )

        predict_plan["pending_same_signal_order_exists"] = (
            same_signal_order_exists
        )

        return True

    def apply_opposing_position_policy(self, order_classes):
        """Close or block opposite live positions before placing new orders."""
        if not self.is_live or not order_classes:
            return order_classes

        response = self.oa2.OpenTrades_exe()
        if response.get("error") != 0:
            for order_class in order_classes:
                self.notify_blocked_order(
                    order_class,
                    self.policy_error_decision("open_trades_fetch_failed"),
                )
            return []

        open_trades = response.get("json", {}).get("trades", [])
        allowed = []
        block_cycle_after_profit = False
        for order_class in order_classes:
            if block_cycle_after_profit:
                self.notify_blocked_order(
                    order_class,
                    self.policy_error_decision(
                        "profitable_opposite_closed_this_cycle"
                    ),
                )
                continue

            plan = getattr(order_class, "exe_order_plan", None) or {}
            decision = OpposingPositionPolicy(self.pair).evaluate(
                plan,
                open_trades,
            )
            action = decision["action"]
            plan["opposing_position_action"] = action
            plan["opposing_position_reason"] = decision["reason"]
            plan["opposing_position_total_pl"] = decision[
                "total_unrealized_pl"
            ]
            plan["opposing_position_max_elapsed_minutes"] = decision[
                "max_elapsed_minutes"
            ]

            if action == "allow":
                allowed.append(order_class)
                continue
            if action == "block":
                self.notify_blocked_order(order_class, decision)
                continue

            if not self.close_policy_trades(decision["close_trades"]):
                decision["reason"] = "opposite_position_close_failed"
                self.notify_blocked_order(order_class, decision)
                continue

            closed_ids = {
                str(trade.get("id")) for trade in decision["close_trades"]
            }
            open_trades = [
                trade for trade in open_trades
                if str(trade.get("id")) not in closed_ids
            ]
            if action == "take_profit_and_block":
                block_cycle_after_profit = True
                self.notify_blocked_order(order_class, decision)
                continue
            if action == "stop_and_reverse":
                allowed.append(order_class)

        return allowed

    @staticmethod
    def policy_error_decision(reason):
        return {
            "action": "block",
            "reason": reason,
            "opposite_trades": [],
            "total_unrealized_pl": 0,
            "max_elapsed_minutes": 0,
            "strength": {},
        }

    def close_policy_trades(self, trades):
        all_succeeded = True
        for trade in trades:
            result = self.oa2.TradeClose_exe(trade.get("id"), None)
            if result.get("error") != 0:
                all_succeeded = False
        return all_succeeded

    def notify_blocked_order(self, order_class, decision):
        plan = getattr(order_class, "exe_order_plan", None) or {}
        direction = int(plan.get("direction") or 0)
        direction_label = "BUY" if direction > 0 else "SELL"
        strength = decision.get("strength") or {}
        memo = str(plan.get("memo", ""))
        if len(memo) > 700:
            memo = memo[:700] + "..."
        try:
            rr = round(
                float(plan.get("tp_range")) / float(plan.get("lc_range")),
                2,
            )
        except (TypeError, ValueError, ZeroDivisionError):
            rr = None
        opposite = decision.get("opposite_trades") or []
        existing = " / ".join(
            (
                f"id={trade.get('id')} units={trade.get('currentUnits')} "
                f"PL={trade.get('unrealizedPL')}円"
            )
            for trade in opposite
        ) or "none"
        notice.line_send(
            "[阻止された]\n"
            f"{self.pair} {direction_label} {plan.get('name')}\n"
            f"target={plan.get('target_price')} units={plan.get('units')} "
            f"TP={plan.get('tp_price')} LC={plan.get('lc_price')}\n"
            f"type={plan.get('type')} mode={plan.get('line_order_mode')} "
            f"entry={plan.get('line_entry_type')} RR={rr}\n"
            f"理由={decision.get('reason')} 判断={decision.get('action')}\n"
            f"既存={existing}\n"
            f"既存合計PL={decision.get('total_unrealized_pl')}円 "
            f"最大経過={decision.get('max_elapsed_minutes', 0):.1f}分\n"
            f"新規score={strength.get('score')} "
            f"priority={strength.get('priority')} "
            f"条件数={strength.get('condition_count')}\n"
            f"memo={memo}"
        )

    def all_update_information_at_out_time(self, candle_analysis_class=None):
        """
        全ての情報を更新する
        :return:
        """
        #  ### Update作業
        # update前
        old_S = [obj.life for obj in self.position_classes]   # 更新前
        # update作業
        for item in self.position_classes:
            if item.life:
                item.update_information_at_out_time(candle_analysis_class)

    def all_update_information(self, candle_analysis_class=None):
        """
        全ての情報を更新する
        :return:
        """
        #  ### Update作業
        # update前
        old_S = [obj.life for obj in self.position_classes]   # 更新前
        # update作業
        for i, item in enumerate(self.position_classes):
            if item.life:
                item.update_information(candle_analysis_class)

        # update後
        # ①　ポジション情報を文字化し、クラスのクラス変数に格納する（代表で[0]に）（LINE送信用）
        if self.position_classes:
            self.position_classes[0].__class__.positions_information = self.position_check()
        # ②　Changeを求めて、差を算出する
        changed = [
            obj
            for obj, old_s in zip(self.position_classes, old_S)
            if old_s is True and obj.life is False
        ]  # 更新によりクローズ（lifeがFalse）になったクラスのリスト
        self.change_remain_position(changed)

        # 更新によりクローズ（lifeがFalse）になったクラスの「コピー」を保存
        closed_positions = [
            copy.deepcopy(obj)
            for obj, old_s in zip(self.position_classes, old_S)
            if old_s is True and obj.life is False
        ]
        self.result_class_arr.extend(closed_positions)

        # 追加の機能
        # 1 ヘッジオーダーの終了
        self.close_hedge_positions()

        return self.position_classes[0].__class__.positions_information

    def close_hedge_positions(self):
        # 両建て状態になっている場合、かつ、両方がプラスになっている両建ての場合、その時点で解消する
        positions = self.position_classes
        exist_positions = []
        # 生きているポジションを取得する
        for i, position in enumerate(positions):
            # 生きているオーダーの取得価格が近い場合
            if position.life:
                # 先に残存するポジションの一覧を生成しておく
                info = {
                    "name": position.name,
                    "target_price": position.plan_json['target_price'],
                    "direction": position.plan_json['direction'],
                    "t_unrealize_pl": position.t_unrealize_pl,
                    "position_class": position
                }
                exist_positions.append(info)
        # 両建てのベストペアを解消する
        best_pair = None
        best_score = -float("inf")
        for l in exist_positions:
            if float(l["direction"]) != 1 or float(l["t_unrealize_pl"]) <= 0:
                continue
            for s in exist_positions:
                if float(s["direction"]) != -1 or float(s["t_unrealize_pl"]) <= 0:
                    continue
                score = float(l["t_unrealize_pl"]) + float(s["t_unrealize_pl"])

                if score > best_score and best_score>0.4:
                    best_score = score
                    best_pair = (l, s)
        if best_pair is None:
            pass
        else:
            l, s = best_pair
            l = l['position_class']
            s = s['position_class']
            te = gene.str_merge("hedge両プラス状態", l.name, l.t_unrealize_pl, l.plan_json['direction'], l.plan_json['units'], ",",
                           s.name, s.t_unrealize_pl, s.plan_json['direction'], s.plan_json['units'])
            print("どっちもプラスの逆方向あり", best_pair, te)
            # tk.line_send(te)

            # クローズする
            if tk.setting_json['hedge_close_on']:
                pass
            else:
                notice.line_send(te)
                l.close_trade()
                s.close_trade()

    def change_remain_position(self, changed):
        """
        オーダーのクローズが発生した場合、
        """
        #  ## 変化に伴う作業
        if changed:
            avg = sum(getattr(obj, "t_pl_pips", 0) for obj in changed) / len(changed)
        else:
            avg = 0  # もしくは None
        if avg < 0:
            # 負けっぽくなっている時は、持っているポジションのどれかのTPをそれにする
            if any(obj.life for obj in self.position_classes):  # 一つでもTrueでもある場合
                remain_classes = [obj for obj in self.position_classes if obj.life is True]
                remain_class_num = len(remain_classes)  # これで割れたら・・？
                for i, item in enumerate(remain_classes):
                    if item.t_state == "OPEN":
                        # できれば解消したポジションと逆の方向のポジションのTPを変更したい。
                        # ただ同時に複数のポジションを解消する可能性もあり、どうしよう
                        # tk.line_send("一部負けが確定したので、所持しているポジションを利確に持っていく ポジ数", remain_class_num)
                        # item.change_tp(abs(avg))  #TP変更
                        # item.del_lc_change()
                        break  # 1つ変更したら終了
            else:
                pass
        else:
            # プラス終了の場合
            pass

        #  #関連オーダーの更新
        # self.linkage_control()

    def life_check(self):
        """
        オーダーが生きているかを確認する。一つでも生きていればＴｒｕｅを返す
        :return:
        """
        life = []
        unlife = []
        comment = ""
        for item in self.position_classes:
            if item.life:
                life.append(item)
                if item.t_state == "OPEN":
                    # print(item.name, "comment", comment, "lcStatus", item.lc_change_status)
                    comment = comment + "," + item.lc_change_status
            else:
                unlife.append(item)
        # 結果を集約する
        if len(life) == 0:
            ans = False  # 一つもLifeがOnでない。
        else:
            ans = True  # 一つでもLifeがある場合はＴｒｕｅ
            # print(" 残っているLIFE", life)

        return {"life_exist": ans, "one_line_comment": comment}

    def find_similar_active_order(self, direction, target_price, threshold_pips=3, source=None, line_strategy=None):
        p = self.p
        for item in self.position_classes:
            if not getattr(item, "life", False):
                continue

            plan = getattr(item, "plan_json", None) or {}
            if int(plan.get("direction", 0)) != int(direction):
                continue
            if source is not None and plan.get("source") != source:
                continue
            if line_strategy is not None and plan.get("line_strategy") != line_strategy:
                continue

            other_price = plan.get("target_price")
            if other_price is None:
                continue

            gap_pips = abs(p.price_to_pips(float(target_price) - float(other_price)))
            if gap_pips <= threshold_pips:
                return {
                    "is_exist": True,
                    "name": item.name,
                    "target_price": float(other_price),
                    "direction": plan.get("direction"),
                    "gap_pips": gap_pips,
                    "o_state": getattr(item, "o_state", None),
                    "t_state": getattr(item, "t_state", None),
                    "source": plan.get("source"),
                    "line_strategy": plan.get("line_strategy"),
                }

        return {"is_exist": False}

    def has_similar_active_order(self, direction, target_price, threshold_pips=3, source=None, line_strategy=None):
        return self.find_similar_active_order(
            direction,
            target_price,
            threshold_pips,
            source=source,
            line_strategy=line_strategy,
        )["is_exist"]

    def position_check(self):
        # 実処理
        open_positions = []
        pending_positions = []
        max_priority_order = 0
        max_priority_position = 0
        max_position_time_sec = 0
        max_order_time_sec = 0
        watching_list = []
        open_class_names = closed_class_names = pending_class_names = ""
        total_pl = 0
        # print("new ")
        for item in self.position_classes:
            # print("new check", item.name, item.life, item.t_state)
            if item.life:  # lifeがTrueの場合、ポジションかオーダーが存在
                # 各情報
                if item.o_state == "Watching":
                    watching_list.append({"name": item.name,
                                          "target": item.plan_json['target_price'],
                                          "direction": item.plan_json['direction'],
                                          "order_time": gene.time_to_str(item.order_register_time),
                                          "state": item.step1_filled,
                                          "keeping": round(item.step1_keeping_second, 0),
                                          })
                    continue
                if item.t_state == "OPEN":
                    # ポジションがある場合、ポジションの情報を取得する
                    # プライオリティも最高値を取得
                    if item.priority > max_priority_position:
                        max_priority_position = item.priority  # ポジションの有る最大のプライオリティを取得する
                    open_positions.append({
                        "name": item.name,
                        "life": item.life,
                        "priority": item.priority,
                        "o_state": item.o_state,
                        "t_state": item.t_state,
                        "pl": getattr(item, "t_pl_pips", 0),
                        "o_json": item.o_json,
                        "o_time": item.o_time,
                        "target_price": item.plan_json.get('target_price'),
                        "direction": item.plan_json.get('direction'),
                        "source": item.plan_json.get('source'),
                        "line_strategy": item.plan_json.get('line_strategy'),
                        "unrealizedPL": item.t_json['unrealizedPL'],
                        "t_time_past_sec": item.t_time_past_sec
                    })
                    # ポジションの所有時間（ポジションがある中で最大）も取得しておく
                    if item.t_time_past_sec > max_position_time_sec:
                        max_position_time_sec = item.t_time_past_sec  # 何分間持たれているポジションか
                    # トータルの含み損益を表示する
                    total_pl = total_pl + float(item.t_unrealize_pl)
                    # オーダー時間リストを作る（表示用）
                    open_class_names = open_class_names + "," + gene.delYearDay(item.o_time) + "(" + str(item.o_json['units']) + ")"
                    # print("  ポジション状態", item.t_id, ",PL:", total_pl)
                elif item.o_state == "PENDING":
                    # オーダーのみ（取得俟ちの場合）取得まち用の配列に入れておく
                    # プライオリティも最高値を取得
                    if item.priority > max_priority_order:
                        max_priority_order = item.priority  # ポジションの有る最大のプライオリティを取得する

                    pending_positions.append({
                        "name": item.name,
                        "life": item.life,
                        "priority": item.priority,
                        "o_state": item.o_state,
                        "t_state": item.t_state,
                        "pl": getattr(item, "t_pl_pips", 0),
                        "o_json": item.o_json,
                        "o_time": item.o_time,
                        "realizedPL": 0,
                        "target_price": item.plan_json.get('target_price'),
                        "direction": item.plan_json.get('direction'),
                        "source": item.plan_json.get('source'),
                        "line_strategy": item.plan_json.get('line_strategy'),
                    })
                    # ポジションの所有時間（ポジションがある中で最大）も取得しておく
                    if item.o_time_past_sec > max_order_time_sec:
                        max_order_time_sec = item.o_time_past_sec  # 何分間オーダー待ちか
                    # オーダー時間リストを作成する（表示用）
                    pending_class_names = pending_class_names + "," + gene.delYearDay(item.o_time) + "(" + str(item.o_json['units']) + ")"
                else:
                    # どうやらt_stateが入っていない状態（オーダーエラーや謎の状態）
                    if item.o_state == "Watching":
                        # tk.line_send("ウォッチング中のオーダーあり　（５分毎処理）")
                        continue
                    print(" 謎の状態(pc_438)　t_state=", item.t_state, ",o_state=", item.o_state, ", 名前:", item.name, ",life=",
                          item.life, ",try_num", item.try_update_num)
                    # tk.line_send(" 謎の状態(分岐前）　t_state=", item.t_state, ",o_state=", item.o_state, ", 名前:", item.name, ",life=", item.life, ",try_num", item.try_update_num)
                    if item.try_update_num <= item.try_update_limit:
                        # まだ何回か確認するまで、LifeはFalseにしない
                        notice.line_send(" 謎の状態(pc_438)　t_state=", item.t_state, ",o_state=", item.o_state, ", 名前:",
                                     item.name,
                                     ",life=", item.life, ",try_num", item.try_update_num, "回目　⇒再トライ")
                        item.count_up_position_check()  # 対象ポジションのtry_update_numをカウントアップする
                    else:
                        item.life_set(False)  # 強制的にクローズ
                        notice.line_send(" 謎の状態(pc_438)　t_state=", item.t_state, ",o_state=", item.o_state, ", 名前:",
                                     item.name,
                                     ",life=", item.life, ",try_num", item.try_update_num, "回目のため終了（lifeFalse)")
            # else:
            #     # Lifeが終わっているもの

        # print(" ★★★★★一時テスト（classPosition)")
        # print(open_positions)
        # print(pending_positions)
        # print("ここまで")
        # 結果の集約
        if len(open_positions) != 0:
            position_exist = True  # ポジションが一つでもOpenになっている場合は、True
        else:
            position_exist = False

        if len(pending_positions) != 0:
            order_exist = True
        else:
            order_exist = False

        # 表示用の名前リストの作成
        name_list = "\n[P待ち]" + pending_class_names + "\n[P中]" + open_class_names + "\n"

        return {
            "position_exist": position_exist,
            "order_exist": order_exist,
            "open_positions": open_positions,
            "max_priority_position": max_priority_position,
            "pending_positions": pending_positions,  # 取得待ちの状態
            "max_priority_order": max_priority_order,
            "max_position_time_sec": max_position_time_sec,
            "max_order_time_sec": max_order_time_sec,
            "total_pl": total_pl,
            "name_list": name_list,
            "watching_list": watching_list
        }

    def catch_up_position_and_del_order(self):
        """
        最初に実行される
        """
        res = self.oa2.OpenTrades_exe()
        if len(res['data']) == 0:
            return 0
        trades_all = res['json']['trades']
        trades = [trade for trade in trades_all if trade.get("instrument") == self.pair]
        print("trades", len(trades), "/", len(trades_all), self.pair)
        print(trades)
        if len(trades) == 0:
            print("現状のポジションなし")
        else:
            # 既存のポジションをひとつづつ見ていく
            for i, exist_position_json in enumerate(trades):
                # クラスのスロットの空きをひとつづつ確認
                print("o,", exist_position_json)
                for class_index, each_exist_class in enumerate(self.position_classes):
                    if each_exist_class.life:
                        # Trueの所には上書きしない
                        continue
                    # Falseのところには代入して、
                    print(class_index)
                    each_exist_class.catch_exist_position(
                        "既存" + str(i),
                        2,
                        5,
                        exist_position_json)
                    break
        self.print_classes_and_count()

    def reset_all_position(self):
        print("  RESET ALL POSITIONS")
        # mainのオアンダクラスのオーダーを削除（API）
        # self.oa.OrderCancel_All_exe()
        # self.oa.TradeAllClose_exe()
        # 両建て用のオアンダクラスのオーダーの削除（API）
        self.oa2.OrderCancel_All_exe()
        # self.oa2.TradeAllClose_exe()

        # プログラム内のクラスの整理
        self.all_update_information()  # 関数呼び出し（アップデート）

    # def linkage_control(self):
    #     """
    #     終わってしまったポジションから、残っているポジションを変えに行く、という方向。
    #     """
    #     margin = 0.01
    #     lc_range = 0.03
    #
    #     # print("PositionControlのリンケージセクション", len(self.position_classes))
    #     for main_position in self.position_classes:
    #
    #         # print("★★", main_position.name, "のリンケージ残存を確認")
    #         if main_position.linkage_done:
    #             # print(main_position.name, " リンケージ調整済み(相手側を調整した,またはされた）")
    #             continue
    #         elif main_position.life and main_position.t_state == "OPEN":
    #             # print(main_position.name, " まだ自分がポジション所持中のため、処理しない", main_position.life, main_position.t_state)
    #             continue
    #         elif main_position.life and main_position.o_state == "PENDING":
    #             # print(main_position.name, " まだ自分がオーダー状態(ポジション前）のため、処理しない")
    #             continue
    #         elif not main_position.life and main_position.t_state == "":
    #             continue
    #         elif main_position.o_json:  # この条件は、テストモードでおかしなことが起きるために追加した（本番悪影響なら消したい）
    #             # print(main_position.o_json)
    #             if main_position.o_json['state'] == "PENDING":
    #                 continue
    #
    #         # elifだと通過してしまう（上のどれかに引っかかってしまっている）ため、独立して記述（o_jsonで引っ掛かってる？）
    #         if main_position.o_state == "Watching":
    #             continue
    #
    #         # これ正しい？
    #         if not main_position.life and main_position.t_state == "CLOSED" and not main_position.linkage_done:
    #             # ★クローズした初回のみ実施！！！？　フラグはここで建てておく。
    #             print("★★初回リンケージチェック", main_position.name, main_position.t_realize_pl)
    #             main_position.linkage_done_func()
    #
    #
    #         #　自身がの勝敗によって、Linkageをするかどうか
    #         # print("       確認用position control", main_position.t_realize_pl)
    #         if float(main_position.t_realize_pl) >= 0:
    #             pass
    #             # print("自身はプラス", main_position.name, main_position.t_realize_pl, main_position.o_state)
    #         else:
    #             pass
    #             # print("自身はマイナス", main_position.name, main_position.t_realize_pl, main_position.o_state)
    #             # continue
    #
    #         # 走査する
    #         if hasattr(main_position, "order_class"):
    #             if hasattr(main_position.order_class, "linkage_order_classes"):
    #                 # print("  ", main_position.name, "のリンケージ")
    #                 if len(main_position.order_class.linkage_order_classes) == 0:
    #                     # print("    linkage登録数０")
    #                     continue
    #             else:
    #                 # print("    linkageのインスタンス変数なし")
    #                 continue
    #
    #             # 本処理(残されたリンケージオーダーへの対応）
    #             for i, linkage_class in enumerate(main_position.linkage_order_classes):
    #                 left_position = next((obj for obj in self.position_classes if obj.name == linkage_class.name), None)
    #                 if left_position is None:
    #                     # print("     レフトポジションがNone")
    #                     continue
    #                 # print("    ", linkage_class.name, "のオーダーが対象", left_position.life, left_position.t_pl_u)
    #                 if left_position is None:
    #                     # print("    ", linkage_class.name, "のリンケージオーダー[", linkage_class.name, "]が対象だが見つからない")
    #                     # tk.line_send("リンケージ先がない物があった.", linkage_class.name, "のリンケージ", linkage_class.name)
    #                     main_position.linkage_done_func()  # 自身のリンケージも終了
    #                     continue
    #                 # 自分自身はポジションあるが、相手がクローズしてしまっている場合
    #                 if left_position.linkage_done:
    #                     # 既に残された側が、
    #                     print("     ", left_position.name, " 既にリンケージ調整され済み", )
    #                     continue
    #
    #                 # メインの種類によって、場合分け？？
    #                 # (0)これ　両建てみたいになっている場合、一つがロスカになった場合、もう一つも、マイナスは避けたい
    #                 # ただし「既存」は色々なデータが欠如してるため不可
    #                 if not "既存" in main_position.name:
    #                     main_pl = float(main_position.t_pl_u)
    #                     if main_pl < 0 and main_position.plan_json['direction'] != left_position.plan_json['direction']:
    #                         if left_position.life and left_position.t_state == "OPEN":
    #                             left_position_take_price = left_position.plan_json['target_price']
    #                             left_position_dir = left_position.plan_json['direction']
    #                             new_lc_range = round(left_position.plan_json['lc_range'] / 1, 3)
    #                             if left_position_dir == 1:
    #                                 new_lc_price = left_position_take_price - new_lc_range  # -正の値で、ロスカを広げる
    #                             else:
    #                                 new_lc_price = left_position_take_price + new_lc_range  # -正の値で、ロスカを広げる
    #                             left_position.linkage_lc_change(new_lc_price)
    #                             main_position.linkage_done_func()
    #
    #
    #                 # (1)メインが、ヘッジ用（負けるか確認のやつ）の場合
    #                 # if "Short" in main_position.name:
    #                 #     pl = float(main_position.t_pl_u)
    #                 #     if pl >= 0:
    #                 #         # print("プラスなので、プラス分を残存しているポジションのLCに設定する")
    #                 #         if left_position.life and left_position.t_state == "OPEN":
    #                 #             left_position_take_price = left_position.plan_json['target_price']
    #                 #             left_position_dir = left_position.plan_json['direction']
    #                 #             new_lc_price = left_position_take_price
    #                 #             new_lc_range = pl
    #                 #             if left_position_dir == 1:
    #                 #                 new_lc_price = new_lc_price - new_lc_range  # -正の値で、ロスカを広げる
    #                 #             else:
    #                 #                 new_lc_price = new_lc_price + new_lc_range  # -正の値で、ロスカを広げる
    #                 #             left_position.linkage_lc_change(new_lc_price)
    #                 #             main_position.linkage_done_func()
    #                 #             # tk.line_send("NewLcPrice", left_position_take_price)
    #                 #     else:
    #                 #         pass
    #                 #         # print("マイナスなので何もしない")
    #                 #
    #                 # elif "シンプルターン_r" in main_position.name:
    #                 #     # print("     rによるリンケージ操作", main_position.name, main_position.linkage_done, main_position.t_state, main_position.t_realize_pl, left_position.t_state)
    #                 #     if float(main_position.t_realize_pl) >= 0:
    #                 #         # プラス域の場合は、問答無用で相手をキャンセルする。
    #                 #
    #                 #         # 相手がまだオーダーの場合、オーダーをクローズする (自分の利確の分をLCにして継続するのもありかも）
    #                 #         if left_position.t_state == "" and left_position.o_state == "PENDING":
    #                 #             # print(" まだlinage先のポジションが成立していないため、オーダー解除")
    #                 #             left_position.close_order()
    #                 #             main_position.linkage_done_func()  # 自身のリンケージも終了
    #                 #             continue
    #                 #
    #                 #         # 相手がポジションの場合、クローズする
    #                 #         if left_position.life and left_position.t_state == "OPEN":
    #                 #             # 相方のポジションがまだある場合（毎なるポジションが想定される）
    #                 #             left_position.close_trade(None)
    #                 #             main_position.linkage_done_func()
    #                 #             continue
    #                 #     else:
    #                 #         # 相手がまだオーダーの場合、オーダーをクローズする (自分の利確の分をLCにして継続するのもありかも）
    #                 #         if left_position.t_state == "" and left_position.o_state == "PENDING":
    #                 #             # print(" まだlinage先のポジションが成立していないため、オーダー解除")
    #                 #             left_position.close_order()
    #                 #             main_position.linkage_done_func()  # 自身のリンケージも終了
    #                 #             continue
    #                 #         # 相手がポジションの場合、プラスが予想される。自身がマイナスなので、相方のマイナス突入は死守。
    #                 #         if left_position.life and left_position.t_state == "OPEN":
    #                 #             left_position_take_price = left_position.plan_json['target_price']
    #                 #             tk.line_send("classPosition477テスト", left_position_take_price)
    #                 #             # print("     残りポジションのTargetPrice", left_position.name, left_position_take_price, left_position_dir)
    #                 #             left_position_dir = left_position.plan_json['direction']
    #                 #             new_lc_price = left_position_take_price
    #                 #             if left_position_dir == 1:
    #                 #                 new_lc_price = new_lc_price - 0.001  # -正の値で、ロスカを広げる
    #                 #             else:
    #                 #                 new_lc_price = new_lc_price + 0.001  # -正の値で、ロスカを広げる
    #                 #             left_position.linkage_lc_change(new_lc_price)
    #                 #             main_position.linkage_done_func()
    #                 #
    #                 # elif "シンプルターン" in main_position.name:
    #                 #     print("     シンプルターンによるリンケージ操作", main_position.name, ",", main_position.t_state, ",",main_position.t_realize_pl, ",",left_position.t_state)
    #                 #     # 相手がポジションの場合、プラスが予想される。自身がマイナスなので、相方のマイナス突入は死守。
    #                 #     if left_position.life and left_position.t_state == "OPEN":
    #                 #         left_position_take_price = left_position.plan_json['target_price']
    #                 #         tk.line_send("classPosition488テスト", left_position_take_price)
    #                 #         print("     残りポジションのTargetPrice", left_position.name, left_position_take_price)
    #                 #         new_lc_price = left_position_take_price
    #                 #         left_position.linkage_lc_change(new_lc_price)
    #                 #         main_position.linkage_done_func()
    #                 #     if left_position.t_state == "" and left_position.o_state == "PENDING":
    #                 #         # print(" まだlinage先のポジションが成立していないため、オーダー解除")
    #                 #         left_position.close_order()
    #                 #         main_position.linkage_done_func()  # 自身のリンケージも終了
    #                 #         continue
    #                 # elif "rシンプルターン" in main_position.name:
    #                 #     print("    rシンプルターン_rが先に終了。rシンプルターンも終わらせないと？？")
    #                 #     # 利確してるときは、確実に終了させる　または、　少しでもマイナスが少ないようにする
    #                 #     if left_position.life and left_position.t_state == "OPEN":
    #                 #         left_position_take_price = left_position.plan_json['target_price']
    #                 #         tk.line_send("classPosition521テスト", left_position_take_price)
    #
    #         else:
    #             pass
    #             print("オーダークラスがない！！！⇒未発行とかそこらへん")


class position_control_for_test(position_control):
    def __init__(self, is_live, filename):
        # 変数の宣言
        print("test用　positioncontorol")
        self.position_classes = []
        self.count_true = 0
        self.oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, tk.environmentl)
        self.oa2 = classOanda.Oanda(tk.accountIDl2, tk.access_tokenl, tk.environmentl)
        self.filename = filename
        # self.temp_file_name = memo

        # 最大所持個数の設定
        self.max_position_num = 25  # 最大でも10個のポジションしかもてないようにする
        self.middle_priority_num = 8  # ミドルプライオリティ(max_position_numのうち）
        self.high_priority_num = 1  # ハイプライオリティのもの（max_position_numのうち）

        self.high_i_to = self.max_position_num
        self.high_i_from = self.high_i_to - self.high_priority_num  # ハイプライオリティスロット(1つ限)の、添え字（最大5スロットの場合、添え字的には4番目スロット）
        self.mid_i_to = self.high_i_from  # python配列のTO指定は「未満」なので、ー１が不要。（以下の場合はマイナスが必要）
        self.mid_i_from = self.mid_i_to - self.middle_priority_num
        self.normal_i_to = self.mid_i_from
        self.normal_i_from = 0

        self.normal_priority_num = self.max_position_num - self.high_priority_num

        # 処理
        for i in range(self.max_position_num):
            # 複数のクラスを動的に生成する。クラス名は「C＋通し番号」とする。
            # クラス名を確定し、クラスを生成する。
            new_name = "c" + str(i)
            self.position_classes.append(testClassPosition.order_information(new_name, is_live, filename))  # 順思想のオーダーを入れるクラス
        self.print_classes_and_count()

    def order_class_add(self, order_classes):
        """
        調査結果を受け取り、他のオーダーを比較し、オーダーを追加するかを判定する
        """
        # ■オーダーのプライオリティの関係
        # 渡されたオーダーの中で、最大のプライオリティのものと、そのプライオリティを算出
        # max_dict = max(order_dic_list, key=lambda d: d["priority"], default=None)
        # max_dict = max(order_dic_list, key=lambda d: d.get("priority", float("-inf")))
        # order_max_priority = max_dict['priority']
        max_instance = max(order_classes, key=lambda x: x.exe_order_plan["priority"])
        order_max_priority = max_instance.exe_order_plan['priority']
        if order_max_priority >=100:
            order_priority_class = "high"
            i_from = self.high_i_from
            i_to = self.high_i_to
        elif order_max_priority >= 10:
            order_priority_class = "mid"
            i_from = self.mid_i_from
            i_to = self.mid_i_to
        else:
            order_priority_class = "normal"
            i_from = self.normal_i_from
            i_to = self.normal_i_to
        allowed_position_slot = self.position_classes[i_from:i_to]  # もらったオーダーの優先度で、許可されたスロット(positionList)
        # for i, order_class in enumerate(allowed_position_slot):
        #     print(" Allowed　", i, "OaMode:", order_class.oa_mode, ",name:", order_class.name, ",life:", order_class.life)
        #     i = i + 1

        # 現在のクラスで、生きている物のみ抽出
        alive_classes = [c for c in allowed_position_slot if hasattr(c, "life") and c.life]
        if len(alive_classes) == 0:
            print(" プログラム上既存のオーダーは存在しないため、オーダー発行へ")
            pass
        elif len(alive_classes) == len(allowed_position_slot):
            # tk.line_send("許容スロットがいっぱい（オーダー発行せず)", len(alive_classes), len(allowed_position_slot))
            self.print_classes_and_count()
            return 0
        elif len(order_classes) + len(alive_classes) > len(allowed_position_slot):
            # tk.line_send("オーダー入れるとオーバーフロー（オーダー発行せず)", len(order_classes), len(alive_classes), len(allowed_position_slot))
            self.print_classes_and_count()
            return 0
        else:
            # 生きているインスタンスの最高値と、指定のプライオリティより高いものを算出
            max_instance = max(alive_classes, key=lambda c: getattr(c, "priority", float("-inf")))
            over_n_classes = [c for c in alive_classes if hasattr(c, "priority") and c.priority > order_max_priority]
            same_n_classes = [c for c in alive_classes if hasattr(c, "priority") and c.priority == order_max_priority]


        # ■現在のクラスの状況の確認
        print("現在のクラスの状況を確認 (classPositionControl)")
        self.print_classes_and_count()

        # クラスに余りがある場合、その中で添え字が一番若いオーダーに上書き、または、追加をする
        line_send = ""
        for order_i, order_class in enumerate(order_classes):
            for class_index, position_slot in enumerate(allowed_position_slot):
                if position_slot.life:
                    # Trueの所には上書きしない
                    continue
                if class_index == self.high_i_from:
                    # ハイクラス用の添え字の場所には、入れない
                    continue

                # Falseのとこで実行する
                res_dic = position_slot.order_plan_registration(order_class)
                break
                # if res_dic['order_id'] == 0:
                #     print("オーダー失敗している（大量オーダー等）")
                #     line_send = line_send + "オーダー失敗(" + str(order_i) + ")" + "\n"
                # else:
                #     # ■オーダーが成功している場合
                #     if res_dic['order_id'] == -1:
                #         # ウォッチオーダー
                #         print("オーダー通知")
                #         # print(res_dic)
                #         # line_sendは利確や損切の指定が無い場合はエラーになりそう（ただそんな状態は基本存在しない）
                #         # TPrangeとLCrangeの表示は「inspection_result_dic」を参照している。
                #         # print(res_dic['order_name'])
                #         # print(res_dic)
                #         line_send = line_send + "◆【" + str(res_dic['order_name']) + "】を即時ポジションなしで発行" + \
                #                     "指定価格:【" + str(round(res_dic['order_result']['price'], 3)) + "】" + \
                #                     ",DIR:" + str(res_dic['order_result']['direction']) + \
                #                     ", 数量:" + str(res_dic['order_result']['units']) + \
                #                     ", TP:" + str(round(res_dic['order_result']['tp_price'], 3)) + \
                #                     "(" + str(round(res_dic['order_result']['tp_range'], 3)) + ")" + \
                #                     ", LC:" + str(round(res_dic['order_result']['lc_price'], 3)) + \
                #                     "(" + str(round(res_dic['order_result']['lc_range'], 3)) + ")" + \
                #                     ", AveMove:" + str(round(res_dic['ref']['move_ave'], 3)) + \
                #                     "[システム]classNo:" + str(class_index) + ",\n"
                #         break
                #     else:
                #         # オーダーの生成完了をLINE通知する
                #         print("オーダー通知", res_dic['order_name'])
                #         print(res_dic)
                #         o_trans = res_dic['order_result']['json']['orderCreateTransaction']  # 短縮のための変数化
                #         line_send = line_send + "【" + str(res_dic['order_name']) + "】,\n" +\
                #                     "指定価格:【" + str(res_dic['order_result']['price']) + "】"+\
                #                     ", 数量:" + str(o_trans['units']) + \
                #                     ", タイプ:" + order_class.ls_type + \
                #                     ", TP:" + str(o_trans['takeProfitOnFill']['price']) + \
                #                     "(" + str(round(abs(float(o_trans['takeProfitOnFill']['price']) - float(res_dic['order_result']['price'])), 3)) + ")" + \
                #                     ", LC:" + str(o_trans['stopLossOnFill']['price']) + \
                #                     "(" + str(round(abs(float(o_trans['stopLossOnFill']['price']) - float(res_dic['order_result']['price'])), 3)) + ")" + \
                #                     ", AveMove:" + str(round(res_dic['ref']['move_ave'], 3)) + \
                #                     ", OrderID:" + str(res_dic['order_id']) + \
                #                     ", 取得価格:" + str(res_dic['order_result']['execution_price']) + "[システム]classNo:" + str(class_index) + ",\n"
                #                     # "\n"
                #         break
        return line_send

    def all_update_information(self, df_row, candle_analysis_class):
        """
        全ての情報を更新する
        :return:
        """
        for item in self.position_classes:
            if item.life:
                item.update_information(df_row, candle_analysis_class)

        # # 関連オーダーの更新
        # self.linkage_control()

    def reset_all_position(self, df_row):
        print("  RESET ALL POSITIONS")
        # mainのオアンダクラスのオーダーを削除（API）
        # self.oa.OrderCancel_All_exe()
        # self.oa.TradeAllClose_exe()
        # 両建て用のオアンダクラスのオーダーの削除（API）
        self.oa2.OrderCancel_All_exe()
        # self.oa2.TradeAllClose_exe()

        # プログラム内のクラスの整理
        self.all_update_information(df_row)  # 関数呼び出し（アップデート）
