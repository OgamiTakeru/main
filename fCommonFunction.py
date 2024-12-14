import json
import tokens as tk
import fPeakInspection as p
import fGeneric as gene
import classOanda
import fPeakInspection as pi


basic_unit = 50000
oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義


def setting_json_read(current_param, param_name):
    """
    実行途中に値を変える。（毎回読み込む）
    この関数一回の実行につき一つのパラメータを読み込むとする
    エラーの場合、現在利用している変数内容をそのまま返却する。
    その為、現在仕様利している変数を引数にとる。
    （変更があった場合、変更を検知して変更した旨も表示できる）
    """
    # JSONファイルを読み込む
    try:
        # JSONファイルを読み込む
        with open(tk.setting_folder_path + 'data.json', "r") as file:
            test = json.load(file)
        ans = test[param_name]
        if ans == current_param:
            pass  # 内容に変更なし
        else:
            pass
            # print("■■■■", param_name, "にてループ途中の内容変更を検知しました")
    except json.JSONDecodeError as e:
        print(f"JSONDecodeError: {e}")
        ans = current_param
    except Exception as e:
        # その他のすべてのエラーをキャッチ
        print(f"予期しないエラーが発生: {e}")
        ans = current_param

    return ans


def order_base(now_price, decision_time):
    """
    引数現在の価格（dicisionPriceの決定のため）、呼ばれたらオーダーのもとになる辞書を返却するのみ
    従来常にBase＝｛price:00・・・｝等書いていたが、行数節約のため、、
    基本はすべて仮の値だが、Unitのみはこれがベースとなる。
    LCCHange内は、執行まで時間が短い順（Time＿After）で記載する（lc_ensure_rangeは広がる方向で書く場合もあり）
    """
    order_base_dic = {
            "target": 0.00,
            "type": "STOP",
            "units": basic_unit,
            "expected_direction": 1,
            "tp": 0.9,
            "lc": 0.10,
            'priority': 0,
            "decision_price": now_price,
            "decision_time": decision_time,
            "name": "",
            "lc_change": [
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.05, "lc_ensure_range": 0.04},
                # 2022-2023は 0.05トリガーにすると、マイナスになる！！
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.06, "lc_ensure_range": 0.04},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.08, "lc_ensure_range": 0.06},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.10, "lc_ensure_range": 0.084},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.12, "lc_ensure_range": 0.10},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.14, "lc_ensure_range": 0.12},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.20, "lc_ensure_range": 0.15},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.25, "lc_ensure_range": 0.20},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.35, "lc_ensure_range": 0.33},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.40, "lc_ensure_range": 0.38},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.50, "lc_ensure_range": 0.43},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.60, "lc_ensure_range": 0.57},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.70, "lc_ensure_range": 0.67},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.80, "lc_ensure_range": 0.77},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.90, "lc_ensure_range": 0.87}
            ],
    }
    new_lc_change = setting_json_read(order_base_dic['lc_change'], 'lc_change')
    order_base_dic['lc_change'] = new_lc_change
    return order_base_dic


def order_base_for_inspection(now_price, decision_time):
    """
    引数現在の価格（dicisionPriceの決定のため）、呼ばれたらオーダーのもとになる辞書を返却するのみ
    従来常にBase＝｛price:00・・・｝等書いていたが、行数節約のため、、
    基本はすべて仮の値だが、Unitのみはこれがベースとなる。
    LCCHange内は、執行まで時間が短い順（Time＿After）で記載する（lc_ensure_rangeは広がる方向で書く場合もあり）
    """
    basic_unit_for_inspection = 10000
    bairitu = 1
    order_base_dic = {
            "target": 0.00,
            "type": "STOP",
            "units": basic_unit_for_inspection,
            "expected_direction": 1,
            "tp": 0.9,
            "lc": 0.03,
            'priority': 0,
            "decision_price": now_price,
            "decision_time": decision_time,
            "name": "",
            "lc_change": [
                # {"lc_change_exe": True, "time_after": 0, "lc_trigger_range": 0.00, "lc_ensure_range": -0.06},
                # {"lc_change_exe": True, "time_after": 0, "lc_trigger_range": 0.050, "lc_ensure_range": 0.03},
                # {"lc_change_exe": True, "time_after": 0 * 5 * 60, "lc_trigger_range": 0.045 * bairitu, "lc_ensure_range": -0.02},
                {"lc_change_exe": True, "time_after": 0, "lc_trigger_range": 0.02 * bairitu, "lc_ensure_range": -0.03},
                {"lc_change_exe": True, "time_after": 0, "lc_trigger_range": 0.05 * bairitu, "lc_ensure_range": 0.001},
                # 2022-2023は 0.05トリガーにすると、マイナスになる！！
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.060 * bairitu, "lc_ensure_range": 0.04 * bairitu},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.08 * bairitu, "lc_ensure_range": 0.06 * bairitu},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.09 * bairitu, "lc_ensure_range": 0.05 * bairitu},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.10 * bairitu, "lc_ensure_range": 0.05 * bairitu},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.15 * bairitu, "lc_ensure_range": 0.10 * bairitu},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.20 * bairitu, "lc_ensure_range": 0.12 * bairitu},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.20 * bairitu, "lc_ensure_range": 0.15 * bairitu},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.30 * bairitu, "lc_ensure_range": 0.20 * bairitu},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.40 * bairitu, "lc_ensure_range": 0.30 * bairitu},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.50 * bairitu, "lc_ensure_range": 0.40 * bairitu},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.60 * bairitu, "lc_ensure_range": 0.50 * bairitu},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.70 * bairitu, "lc_ensure_range": 0.60 * bairitu},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.80 * bairitu, "lc_ensure_range": 0.70 * bairitu},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.90 * bairitu, "lc_ensure_range": 0.80 * bairitu},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 1.00 * bairitu, "lc_ensure_range": 0.90 * bairitu}

                # {"lc_change_exe": True, "time_after": 0, "lc_trigger_range": 0.032, "lc_ensure_range": -0.06},
                # {"lc_change_exe": True, "time_after": 0, "lc_trigger_range": 0.050, "lc_ensure_range": -0.03},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.01, "lc_ensure_range": -0.08},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.038, "lc_ensure_range": -0.04},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.048, "lc_ensure_range": 0.04},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.07, "lc_ensure_range": 0.05},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.10, "lc_ensure_range": 0.075},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.35, "lc_ensure_range": 0.33},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.50, "lc_ensure_range": 0.43},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.60, "lc_ensure_range": 0.57},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.70, "lc_ensure_range": 0.67},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.80, "lc_ensure_range": 0.77},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.90, "lc_ensure_range": 0.87}
            ],
    }
    return order_base_dic


def order_base_cross(now_price, decision_time):
    """
    引数現在の価格（dicisionPriceの決定のため）、呼ばれたらオーダーのもとになる辞書を返却するのみ
    従来常にBase＝｛price:00・・・｝等書いていたが、行数節約のため、、
    基本はすべて仮の値だが、Unitのみはこれがベースとなる。
    LCCHange内は、執行まで時間が短い順（Time＿After）で記載する（lc_ensure_rangeは広がる方向で書く場合もあり）
    """
    return {
            "target": 0.00,
            "type": "STOP",
            "units": basic_unit,
            "expected_direction": 1,
            "tp": 0.9,
            "lc": 0.10,
            'priority': 0,
            "decision_price": now_price,
            "decision_time": decision_time,
            "name": "",
            "lc_change": [
                # {"lc_change_exe": True, "time_after": 0, "lc_trigger_range": 0.00, "lc_ensure_range": -0.06},
                # {"lc_change_exe": True, "time_after": 0, "lc_trigger_range": 0.050, "lc_ensure_range": 0.03},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.05, "lc_ensure_range": 0.04},
                # 2022-2023は 0.05トリガーにすると、マイナスになる！！
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.06, "lc_ensure_range": 0.04},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.08, "lc_ensure_range": 0.06},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.10, "lc_ensure_range": 0.084},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.12, "lc_ensure_range": 0.10},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.14, "lc_ensure_range": 0.12},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.20, "lc_ensure_range": 0.15},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.25, "lc_ensure_range": 0.20},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.35, "lc_ensure_range": 0.33},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.40, "lc_ensure_range": 0.38},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.50, "lc_ensure_range": 0.43},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.60, "lc_ensure_range": 0.57},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.70, "lc_ensure_range": 0.67},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.80, "lc_ensure_range": 0.77},
                {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.90, "lc_ensure_range": 0.87}

                # {"lc_change_exe": True, "time_after": 0, "lc_trigger_range": 0.032, "lc_ensure_range": -0.06},
                # {"lc_change_exe": True, "time_after": 0, "lc_trigger_range": 0.050, "lc_ensure_range": -0.03},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.01, "lc_ensure_range": -0.08},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.038, "lc_ensure_range": -0.04},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.048, "lc_ensure_range": 0.04},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.07, "lc_ensure_range": 0.05},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.10, "lc_ensure_range": 0.075},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.35, "lc_ensure_range": 0.33},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.50, "lc_ensure_range": 0.43},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.60, "lc_ensure_range": 0.57},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.70, "lc_ensure_range": 0.67},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.80, "lc_ensure_range": 0.77},
                # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.90, "lc_ensure_range": 0.87}
            ],
    }


def make_trid_order(plan):
    """
    トラップ&リピートイフダンの注文を入れる
    :param plan{
        decision_price: 参考値だが、入れておく
        units: １つのグリッドあたりの注文数。
        (不要）ask_bid: 1の場合買い(Ask)、-1の場合売り(Bid) 引数時は['direction']になってしまっている。
        start_price: 130.150のような小数点三桁で指定。（メモ：APIで渡す際は小数点３桁のStr型である必要がある。本関数内で自動変換）
                     トラリピの最初の価格を指定する
        expected_direction: 1 or -1
        grid: 格子幅の設定。またこれは基本的に各LCRangeとほぼ同等となる。
        lc_range: ある場合、全てのに対して同じものが適応される
        start_price_lc: 検討中。
        num: end_priceがない場合は必須。何個分のグリッドを設置。
        end_price:　numがない場合は必須。numと両方ある場合は、こちらが優先。StartPriceからEndPriceまで設置する
        type:　"STOP" 基本は順張りとなるため、ストップになるはずだけれど。
    }

    :return: 上記の情報をまとめてArrで。オーダーミス発生(オーダー入らず)した場合は、辞書内cancelがTrueとなる。
    ■　結果は配列で返される。
    """
    # startPriceを取得する
    if 'start_price' in plan:
        start_price = plan['start_price']
        for_price = start_price  # for分で利用する価格
    else:
        print(" startPriceが入っていません")

    # NUMを求める（そっちの方が計算しやすいから。。endpriceの場合、ループ終了条件が、買いか売りかによって分岐が必要になる）
    if 'num' in plan:
        # numが指定されている場合は、純粋にそれを指定する
        num = plan['num']
    else:
        # numが指定されていない場合、EndpriceとstartPriceとの差分をgridで割った数がNumとなる
        if 'end_price' in plan and plan['end_price'] > 1:
            # エンドプライスが入っており、異常値（rangeを表すような極小値）が入っていないか
            num = int(abs(start_price - plan['end_price']) / plan['grid'])
        else:
            print("Endpriceが入ってない、またはEndpriceが異常値です")

    order_result_arr = []
    for i in range(num):
        # ループでGrid分を加味した価格でオーダーを打っていく。ただし、初回のみはLC価格が例外
        if i == 100:
            # 初回のみLCは広めにする？
            pass
        else:
            # 指定価格の設定
            each_order = order_finalize({  # オーダー２を作成
                "name": "TRID" + str(plan['expected_direction']) + str(i),
                "order_permission": True,
                "decision_price": plan['decision_price'],  # ★
                "target": for_price,  # 価格で指定する
                "decision_time": 0,  #
                "tp": plan['grid'] * 0.8,
                "lc": 0.06 if not('lc_range' in plan) else plan['lc_range'],
                "units": plan['units'],
                "expected_direction": plan['expected_direction'],
                "stop_or_limit": 1,  # ★順張り
                "trade_timeout_min": 1800,
                "priority": 0,
                "remark": "test",
            })
            # オーダーの蓄積
            order_result_arr.append(each_order)

            # 次のループへ
            for_price = round(for_price + (plan['expected_direction'] * plan['grid']), 3)

    return order_result_arr


def get_now_mid_price():
    """
    各関数の行数削減（特にエラー対応）のため、関数に出す
    ・とりあえずミドル価格を返す
    ・エラーの場合、このループをおしまいにする？それともっぽい値を返却する？
    """
    # print("   NowPrice関数@ CommonFunction")
    price_dic = oa.NowPrice_exe("USD_JPY")
    if price_dic['error'] == -1:  # APIエラーの場合はスキップ
        print("      API異常発生の可能性")
        return -1  # 終了
    else:
        price_dic = price_dic['data']
    return price_dic['mid']


def information_fix(dic_args):
    """
    各解析関数から呼ばれる。各解析関数が検証から呼ばれているか、本番から呼ばれているかを判定する
    第二引数存在し、かつそれがpeaks辞書の配列ではない場合、パラメータモードとする
    :param dic_args: 最大３種類
        df_r : 必ず来る。対象のデータ振れむ
        params: パラメータ（オプション）　検証や条件の切り替えで利用する
        peaks: df_sから算出　または　呼び出し元から渡される（何回もPeaks関数を実行しないようにするため）
        inspection_params: 検証用のパラメータ
        参考
        params = [
            {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2}
            {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2}
        ]
        inspection_params = [
            {""}
        ]

    :return: {"peaks":peaks, "df_r": df_r, "params": パラメータList or None}
         注　Peakが渡された場合は、そのままを返却するする。（上書きしないため、渡されたdf_rと齟齬がある可能性も０ではない）
    """
    s = "        "  # 5個分
    print(s, "<引数整流化> @CommonFunction")

    # データフレームに関する処理
    if not "df_r" in dic_args:
        print(s, "Df_rがありません（異常です）")

    # ピークスに関する処理（生成or既存のものを利用)
    if "peaks" in dic_args:  # Peakの算出等を行う
        print(s, "Peaks既存")
        peaks = dic_args["peaks"]
    else:
        peaks_info = p.make_peaks_finalize(dic_args['df_r'], 15)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝）を指定）
        # peaks_info = p.peaks_collect_main_not_skip(dic_args['df_r'], 15)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝）を指定）
        peaks = peaks_info['all_peaks']
        if len(peaks) < 4:
            print("　ピークの個数が足りない(エラーではない)")
            return {"df_r": dic_args['df_r'], "peaks": [], "params": {}, "inspection_params": {}}
        else:
            # 'time': '2024/10/31 05:35:00', 'peak': np.float64(153.365), 'peak_peak': np.float64(
            #     153.344), 'time_old': '2024/10/31 05:30:00', 'peak_old': np.float64(153.383), 'direction': np.float64(
            #     -1.0), 'body_ave': np.float64(0.025), 'count': 2, 'gap': np.float64(0.018),
            print(s, "<対象>")
            print(s, "Latest", pi.delete_peaks_information_for_print(peaks[0]))
            print(s, "river ", pi.delete_peaks_information_for_print(peaks[1]))
            print(s, "turn", pi.delete_peaks_information_for_print(peaks[2]))
            print(s, "flop3", pi.delete_peaks_information_for_print(peaks[3]))
            print(s, "すべて")
        # gene.print_arr(peaks, 5)

    # 以下はパラメータ用（あまり使っていない）
    if "params" in dic_args:  # paramsが引数の中にある場合 (検証モードや条件切り替え等で利用）
        params = dic_args['params']
    else:
        params = None

    if "inspection_params" in dic_args:
        inspection_params = dic_args['inspection_params']
    else:
        inspection_params = None

    return {"df_r": dic_args['df_r'], "peaks": peaks, "params": params, "inspection_params": inspection_params}


def order_finalize(order_base_info):
    """
    オーダーを完成させる。TPRangeとTpPrice、Marginとターゲットプライスのどちらかが入ってれば完成させたい。
    martinとTarget価格をいずれかの受け取り。両方受け取ると齟齬が発生する可能性があるため、片方のみとする
    :param order_base_info:必須
    order_base = {
        "expected_direction": river['direction'] * -1,  # 必須
        "decision_time": river['time'],  # 任意（アウトプットのエクセルの時に使う　それ以外は使わない）
        "decision_price": river['peak'],  # 必須（特に、targetの指定がRangeで与えられた場合に利用する）
        "target": 価格 or Range で正の値  # 80以上の値は価格とみなし、それ以外ならMargin(現価格＋marginがターゲット価格）とする
        "tp": 価格 or Rangeで正の値,  # 80以上の値は価格とみなし、それ以外ならRange(target価格+Range）とする
        "lc": 価格　or Rangeで正の値  # 80以上の値は価格とみなし、それ以外ならRange(target価格+Range）とする
        #オプション
        ""
    }
    いずれかが必須
    # 注文方法は、Typeでもstop_or_limitでも可能
        "stop_or_limit": 1 or -1,  # 必須 (1の場合順張り＝Stop,-1の場合逆張り＝Limit
        type = "STOP" "LIMIT" 等直接オーダーに使う文字列
    :return:　order_base = {
        "stop_or_limit": stop_or_limit,  # 任意（本番ではtype項目に置換して別途必要になる。計算に便利なように数字で。）
        "type":"STOP" or "LIMIT",# 最終的にオーダーに必須（OandaClass）
        "expected_direction": # 検証で必須（本番ではdirectionという名前で別途必須になる）
        "decision_time": # 任意
        "decision_price": # 検証で任意
        "position_margin": # 検証で任意
        "target_price": # 検証で必須　運用で任意(複数Marginで再計算する可能性あり)
        "lc_range": # 検証と本番で必須
        "tp_range": # 検証と本番で必須
        "tp_price": # 任意
        "lc_price": # 任意
        "direction", # 最終的にオーダーに必須（OandaClass）
        "price":,  # 最終的にオーダーに必須（OandaClass）
        "trade_timeout_min,　必須（ClassPosition）
        "order_permission"  必須（ClassPosition）
    }
    """
    # 価格や通貨に依存する物たち
    dependence_price_or_range_criteria = 80  # ドル円の場合、80以上は価格とみなし、それ以下はrangeとみなす
    dependence_tp_lc_margin = 0.02  # 最低限の幅を保つためのもの。ドル円の場合0.02円(2pips) (LC価格とTarget価格が同値となった時の調整)

    # ⓪必須項目がない場合、エラーとする
    if not ('expected_direction' in order_base_info) or not ('decision_price' in order_base_info):
        print("　　　　エラー（項目不足)", 'expected_direction' in order_base_info,
              'decision_price' in order_base_info, 'decision_time' in order_base_info)
        return -1  # エラー

    # 0 注文方式を指定する
    if not ('stop_or_limit' in order_base_info) and not ("type" in order_base_info):
        print(" ★★オーダー方式が入力されていません")
    else:
        if 'type' in order_base_info:
            if order_base_info['type'] == "STOP":
                order_base_info['stop_or_limit'] = 1
            elif order_base_info['type'] == "LIMIT":
                order_base_info['stop_or_limit'] = -1
            elif order_base_info['type'] == "MARKET":
                print("    Marketが指定されてます。targetは価格が必要です。Rangeを指定すると['stop_or_limit']がないエラーになる")
                pass
        elif 'stop_or_limit' in order_base_info:
            order_base_info['type'] = "STOP" if order_base_info['stop_or_limit'] == 1 else "LIMIT"

    # ①TargetPriceを確実に取得する
    if not ('target' in order_base_info):
        # どっちも入ってない場合、Error
        print("    ★★★target(Rangeか価格か）が入力されていません")
    elif order_base_info['target'] >= dependence_price_or_range_criteria:
        # targetが８０以上の数字の場合、ターゲット価格が指定されたとみなす
        order_base_info['position_margin'] = round(abs(order_base_info['decision_price'] - order_base_info['target']), 3)
        order_base_info['target_price'] = order_base_info['target']
        # print("    ★★target 価格指定", order_base['target'], abs(order_base['decision_price']), order_base['target_price'])
    elif order_base_info['target'] < dependence_price_or_range_criteria:
        # targetが80未満の数字の場合、PositionまでのMarginが指定されたとみなす（負の数は受け入れない）
        if order_base_info['target'] < 0:
            print("   targetに負のRangeが指定されています。ABSで使用します（正の値を計算で調整）")
            order_base_info['target'] = abs(order_base_info['target'])
        order_base_info['position_margin'] = round(order_base_info['target'], 3)
        order_base_info['target_price'] = order_base_info['decision_price'] + \
                                          (order_base_info['target'] * order_base_info['expected_direction'] * order_base_info[
                                         'stop_or_limit'])
        # print("    t★arget Margin指定", order_base['target'], abs(order_base['decision_price']), order_base['target_price'])
    else:
        print("     Target_price PositionMarginどっちも入っている")

    # ② TP_priceとTP_Rangeを求める
    if not ('tp' in order_base_info):
        print("    ★★★TP情報が入っていません（利確設定なし？？？）")
        order_base_info['tp_range'] = 0  # 念のため０を入れておく（価格の指定は絶対に不要）
    elif order_base_info['tp'] >= dependence_price_or_range_criteria:
        # print("    TP 価格指定")
        # 80以上の数字は、Price値だと認識。Priceの設定と、Rangeの算出と設定を実施。
        #    ただし、偶然Target_Priceと同じになる(秒でTPが入ってしまう)可能性あるため、target_price-価格が0.02未満の場合は調整する。
        if abs(order_base_info['target_price'] - order_base_info['tp']) < dependence_tp_lc_margin:
            # 調整を行う（Rangeを最低の0.02に設定し、そこから改めてLC＿Priceを算出する）
            print("  ★★TP価格とTarget価格が同値となったため、調整あり(0.02)")
            order_base_info['tp_range'] = dependence_tp_lc_margin
            order_base_info['tp_price'] = round(order_base_info['target_price'] + (
                    order_base_info['tp_range'] * order_base_info['expected_direction']), 3)
        else:
            # 調整なしでOK
            order_base_info['tp_price'] = round(order_base_info['tp'], 3)
            order_base_info['tp_range'] = abs(order_base_info['target_price'] - order_base_info['tp'])
    elif order_base_info['tp'] < dependence_price_or_range_criteria:
        # print("    TP　Range指定")
        # 80未満の数字は、Range値だと認識。Rangeの設定と、Priceの算出と設定を実施
        order_base_info['tp_price'] = round(order_base_info['target_price'] + (order_base_info['tp'] * order_base_info['expected_direction']), 3)
        order_base_info['tp_range'] = order_base_info['tp']

    # ③ LC_priceとLC_rangeを求める
    if not ('lc' in order_base_info):
        # どっちも入ってない場合、エラー
        print("    ★★★LC情報が入っていません（利確設定なし？？）")
    elif order_base_info['lc'] >= dependence_price_or_range_criteria:
        # print("    LC 価格指定")
        # 80以上の数字は、Price値だと認識。Priceの設定と、Rangeの算出と設定を実施。
        #     ただし、偶然Target_Priceと同じになる(秒でLCが入ってしまう)可能性あるため、target_price-価格が0.02未満の場合は調整する。
        if abs(order_base_info['target_price'] - order_base_info['lc']) < dependence_tp_lc_margin:
            # 調整を行う（Rangeを最低の0.02に設定し、そこから改めてLC＿Priceを算出する）
            print("  ★★LC価格とTarget価格が同値となったため、調整あり(0.02)")
            order_base_info['lc_range'] = dependence_tp_lc_margin
            order_base_info['lc_price'] = round(order_base_info['target_price'] - (
                    order_base_info['lc_range'] * order_base_info['expected_direction']), 3)
        else:
            # 調整なしでOK
            order_base_info['lc_price'] = round(order_base_info['lc'], 3)
            order_base_info['lc_range'] = abs(order_base_info['target_price'] - order_base_info['lc'])
    elif order_base_info['lc'] < dependence_price_or_range_criteria:
        # print("    LC RANGE指定")
        # 80未満の数字は、Range値だと認識。Rangeの設定と、Priceの算出と設定を実施
        order_base_info['lc_price'] = round(order_base_info['target_price'] - (order_base_info['lc'] * order_base_info['expected_direction']), 3)
        order_base_info['lc_range'] = order_base_info['lc']

    # 最終的にオーダーで必要な情報を付与する(項目名を整えるためにコピーするだけ）。LimitかStopかを算出
    order_base_info['direction'] = order_base_info['expected_direction']
    order_base_info['price'] = order_base_info['target_price']
    order_base_info['trade_timeout_min'] = order_base_info['trade_timeout_min'] if 'trade_timeout_min' in order_base_info else 60
    order_base_info['order_permission'] = order_base_info['order_permission'] if 'order_permission' in order_base_info else True
    # 表示形式の問題で、、念のため（機能としては不要）
    order_base_info['decision_price'] = float(order_base_info['decision_price'])

    # ordered_dict = OrderedDict((key, order_base_info[key]) for key in order)
    order_base_info = sorted_dict = {key: order_base_info[key] for key in sorted(order_base_info)}

    # 名前の最後尾に時刻（決心時刻）をつける
    order_base_info['name'] = order_base_info['name'] + "_" + str(gene.delYearDay(order_base_info['decision_time']))

    # コマンドラインで見にくいので、表示の順番を変えたい、、、（書き方雑だけど）
    # ★コマンドラインで見にくいので、表示の順番を変えたい、、、（書き方雑だけど）
    # NAME
    temp = order_base_info['name']  # いったん保存
    del order_base_info["name"]
    order_base_info['name'] = temp

    temp = order_base_info['trade_timeout_min']  # いったん保存
    del order_base_info["trade_timeout_min"]
    order_base_info['trade_timeout_min'] = temp

    temp = order_base_info['tp_range']  # いったん保存
    del order_base_info["tp_range"]
    order_base_info['tp_range'] = temp

    temp = order_base_info['tp']  # いったん保存
    del order_base_info["tp"]
    order_base_info['tp'] = temp

    temp = order_base_info['price']  # いったん保存
    del order_base_info["price"]
    order_base_info['price'] = temp

    temp = order_base_info['target']  # いったん保存
    del order_base_info["target"]
    order_base_info['target'] = temp

    # temp = order_base_info['stop_or_limit']  # いったん保存
    # del order_base_info["stop_or_limit"]
    # order_base_info['stop_or_limit'] = temp

    temp = order_base_info['priority']  # いったん保存
    del order_base_info["priority"]
    order_base_info['priority'] = temp

    temp = order_base_info['position_margin']  # いったん保存
    del order_base_info["position_margin"]
    order_base_info['position_margin'] = temp
    #
    temp = order_base_info['order_permission']  # いったん保存
    del order_base_info["order_permission"]
    order_base_info['order_permission'] = temp

    # LC_RAGE
    temp = order_base_info['lc_range']  # いったん保存
    del order_base_info["lc_range"]
    order_base_info['lc_range'] = temp
    # LC
    temp = order_base_info['lc']  # いったん保存
    del order_base_info["lc"]
    order_base_info['lc'] = temp
    # 方向
    temp = order_base_info['expected_direction']  # いったん保存
    del order_base_info["expected_direction"]
    order_base_info['expected_direction'] = temp
    # decisionPrice
    temp = order_base_info['decision_price']  # いったん保存
    del order_base_info["decision_price"]
    order_base_info['decision_price'] = temp
    # LCChange(これが最後尾にしたい）
    temp = order_base_info['lc_change']  # いったん保存
    del order_base_info["lc_change"]
    order_base_info['lc_change'] = temp

    return order_base_info
