import pandas as pd
import datetime
import fBlockInspection as f  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import making as mk
import fDoublePeaks as dp
import fGeneric as f

# グローバルでの宣言
oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義
print(oa.NowPrice_exe("USD_JPY"))
gl_start_time = datetime.datetime.now()
gl_now = datetime.datetime.now().replace(microsecond=0)  # 現在の時刻を取得
gl_now_str = str(gl_now.month).zfill(2) + str(gl_now.day).zfill(2) + "_" + \
            str(gl_now.hour).zfill(2) + str(gl_now.minute).zfill(2) + "_" + str(gl_now.second).zfill(2)


# 解析パート
def analysis_part(df_r, params):
    # print("★★解析パート")
    # return dp.turn1Rule(df_r)
    # return dp.beforeDoublePeak(df_r, params)
    # return dp.DoublePeak(df_r, params)
    # return dp.DoublePeak_4peaks(df_r, params)
    return dp.DoublePeakBreak(df_r, params)
    # return dp.now_position(df_r)
    # prac.turn_inspection_main(df_r)


# 検証パート
def confirm_part(df_r, ana_ans):
    """

    :param df_r: 検証用のデータフレーム（関数内で5S足のデータを別途取得する場合は利用しない）
    :param ana_ans: 解析の結果、どの価格でポジションを取得するか等の情報 以下の辞書を受け取る
    order_base = {
        "stop_or_limit": stop_or_limit,  # 〇
        "expected_direction": expected_direction,  # 〇
        "decision_time": river['time'],  # 〇
        "decision_price": river['peak'],  # ×　
        "position_margin": position_margin,  # ×
        "target_price": target_price,  # 〇
        "lc_range": lc,  #　〇
        "tp_range": tp,  # 〇
        "tp_price": target_price + (tp * expected_direction),  # ×
        "lc_price": target_price - (lc * expected_direction),  # ×
    }
    :return:　return内を参照。
    """
    print("★★確認パート")
    # 検証パートは古いのから順に並び替える（古いのが↑、新しいのが↓）
    df = df_r.sort_index(ascending=True)  # 正順に並び替え（古い時刻から新しい時刻に向けて１行筒検証する）
    df = df[:10]
    confirm_start_time = df.iloc[0]['time']  # 検証開始時間を入れる
    # 検証用の５秒足データを取得し、荒い足のdfに上書きをする（上書きにすることで、この部分をコメントアウトすれば変数名を変えなくても対応可能）
    params = {
        "granularity": "S5",
        "count": 550,  #約４５分。５秒足×550足分
        "from": confirm_start_time,
    }
    df = oa.InstrumentsCandles_multi_exe("USD_JPY", params, 1)['data']
    # print(" 検証対象")
    # print(df.head(5))

    # ★設定　基本的に解析パートから持ってくる。 (150スタート、方向1の場合、DFを巡回して150以上どのくらい行くか)
    position_target_price = ana_ans['target_price']  # マージンを考慮
    start_time = df.iloc[0]['time_jp']  # ポジション取得決心時間（正確には、５分後）
    expected_direction = ana_ans['expected_direction']  # 進むと予想した方向(1の場合high方向がプラス。
    lc_range = ana_ans['lc_range']  # ロスカの幅（正の値）
    tp_range = ana_ans['tp_range']  # 利確の幅（正の値）

    # 即時のポジションかを判定する
    if df.iloc[0]['open'] - 0.008 < position_target_price < df.iloc[0]['open'] + 0.008:  # 多少の誤差（0.01)は即時ポジション。マージンがない場合は基本即時となる。
        # print(" 即時ポジション", position_target_price, expect_direction)
        position_time = df.iloc[0]['time_jp']
        position = True
    else:
        # print(" ポジション取得待ち", position_target_price, expect_direction)
        position_time = 0
        position = False

    # 検証する
    max_upper = 0
    max_lower = 0
    max_upper_time = 0
    max_upper_past_sec = 0
    max_lower_time = 0
    max_lower_past_sec = 0
    lc_out = False
    tp_out = False
    lc_time = 0
    lc_time_past = 0
    lc_res = 0
    tp_time = 0
    tp_time_past = 0
    tp_res = 0
    max_upper_all_time = 0
    max_lower_all_time = 0
    max_upper_time_all_time = 0
    max_upper_past_sec_all_time = 0
    max_lower_time_all_time = 0
    max_lower_past_sec_all_time = 0
    end_time_of_inspection = 0
    for i, item in df.iterrows():
        if position:
            # ■　ポジションがある場合の処理
            # ①共通　スタートよりも最高値が高い場合、それはアッパー域。逆にロア域分（プラス域、マイナス域には最後に変換）
            upper = item['high'] - position_target_price if position_target_price < item['high'] else 0
            lower = position_target_price - item['low'] if position_target_price > item['low'] else 0
            end_time_of_inspection = item['time_jp']  # 最後に検証した時刻を、検証終了時刻として保管（ループを全て行う場合）

            # ②最大値や最小値を求めていく
            if lc_out or tp_out:
                # 一回ポジション取得⇒LCかTPありの状態（既にポジションが解消されているような状態）
                # 注意！position変数は、集計に利用するため、一度TrueにしたらFalseにはしないようにする
                # ②-1 利確orロスカが既に入っている場合は、ループは最後まで回し、全期間での最大最小を求める（24/2/14まではBreakしていた）
                if upper > max_upper_all_time:
                    # 全期間でも取得する
                    max_upper_all_time = upper  # 最大値入れ替え
                    max_upper_time_all_time = item['time_jp']
                    max_upper_past_sec_all_time = f.seek_time_gap_seconds(item['time_jp'], start_time)
                if lower > max_lower_all_time:
                    # 全期間でも取得する
                    max_lower_all_time = lower  # 最小値入れ替え
                    max_lower_time_all_time = item['time_jp']
                    max_lower_past_sec_all_time = f.seek_time_gap_seconds(item['time_jp'], start_time)
            else:
                # ②-2 利確またはロスカが既に入っている場合
                if upper > max_upper:
                    max_upper = upper # 最大値入れ替え
                    max_upper_time = item['time_jp']
                    max_upper_past_sec = f.seek_time_gap_seconds(item['time_jp'], start_time)
                    # 全期間でも取得する
                    max_upper_all_time = upper
                    max_upper_time_all_time = item['time_jp']
                    max_upper_past_sec_all_time = f.seek_time_gap_seconds(item['time_jp'], start_time)
                if lower > max_lower:
                    max_lower = lower  # 最小値入れ替え
                    max_lower_time = item['time_jp']
                    max_lower_past_sec = f.seek_time_gap_seconds(item['time_jp'], start_time)
                    # 全期間でも取得する
                    max_lower_all_time = lower
                    max_lower_time_all_time = item['time_jp']
                    max_lower_past_sec_all_time = f.seek_time_gap_seconds(item['time_jp'], start_time)
                # ロスカ分を検討する
                if lc_range != 0:  # ロスカ設定ありの場合、ロスカに引っかかるかを検討
                    lc_jd = lower if expected_direction == 1 else upper  # 方向が買(expect=1)の場合、LCはLower方向。
                    if lc_jd > lc_range:  # ロスカが成立する場合
                        # print(" 　LC★", item['time_jp'], lc_r)
                        lc_out = True
                        lc_time = item['time_jp']
                        lc_time_past = f.seek_time_gap_seconds(item['time_jp'], start_time)
                        lc_res = lc_range
                if tp_range != 0:  # TP設定あるの場合、利確に引っかかるかを検討
                    tp_jd = upper if expected_direction == 1 else lower  # 方向が買(expect=1)の場合、LCはLower方向。
                    if tp_jd > tp_range:
                        if lc_out:
                            pass
                            # LC Range成立時でもTPと並立カウントするか、上書きとする場合（このブロックをコメントイン）
                            # print(" 　TP★", item['time_jp'], tp_range)
                            # tp_out = True
                            # tp_time = item['time_jp']
                            # tp_time_past = f.seek_time_gap_seconds(item['time_jp'], start_time)
                            # tp_res = tp_range
                            # # LCを取り下げる場合は以下をコメントイン
                            # # print(" 　LC★", item['time_jp'], lc_range)
                            # lc_out = False
                            # lc_time = 0
                            # lc_time_past = 0
                            # lc_res = 0
                        else:
                            # LC成立時はLCを優先する（厳しめ）
                            # print(" 　TP★", item['time_jp'], tp_range)
                            tp_out = True
                            tp_time = item['time_jp']
                            tp_time_past = f.seek_time_gap_seconds(item['time_jp'], start_time)
                            tp_res = tp_range
        else:
            # ■ポジションがない場合の動き(ポジションを取得する）
            if item['low'] < position_target_price < item['high']:
                position_time = item['time_jp']
                position = True  # 集計に利用するため、一度TrueにしたらFalseにはしないようにする
                # print(" 　取得★", item['time_jp'], position_target_price)

    # 情報整理＠ループ終了後（directionに対してLow値をHigh値が、金額的にプラスかマイナスかを変更する）
    if expected_direction == 1:  # 買い方向を想定した場合
        max_minus = round(max_lower, 3)
        max_minus_time = max_lower_time
        max_minus_past_sec = max_lower_past_sec
        max_plus = round(max_upper, 3)
        max_plus_time = max_upper_time
        max_plus_past_sec = max_upper_past_sec
        # 検証の全期間
        max_minus_all_time = round(max_lower_all_time, 3)
        max_minus_time_all_time = max_lower_time_all_time
        max_minus_past_sec_all_time = max_lower_past_sec_all_time
        max_plus_all_time = round(max_upper_all_time, 3)
        max_plus_time_all_time = max_upper_time_all_time
        max_plus_past_sec_all_time = max_upper_past_sec_all_time
    else:
        max_minus = round(max_upper, 3)
        max_minus_time = max_upper_time
        max_minus_past_sec = max_upper_past_sec
        max_plus = round(max_lower, 3)
        max_plus_time = max_lower_time
        max_plus_past_sec = max_lower_past_sec
        # 検証の全期間
        max_minus_all_time = round(max_upper_all_time, 3)
        max_minus_time_all_time = max_upper_time_all_time
        max_minus_past_sec_all_time = max_upper_past_sec_all_time
        max_plus_all_time = round(max_lower_all_time, 3)
        max_plus_time_all_time = max_lower_time_all_time
        max_plus_past_sec_all_time = max_lower_past_sec_all_time

    print("買い方向", expected_direction, "最大プラス", max_plus, max_plus_time,  "最大マイナス", max_minus, max_minus_time)

    return {
        "position": position,
        "position_price": position_target_price,
        "position_time": position_time,
        "end_time_of_inspection": end_time_of_inspection,
        "max_plus": max_plus,
        "max_plus_time": max_plus_time,
        "max_plus_past_time": max_plus_past_sec,
        "max_minus": max_minus,
        "max_minus_time": max_minus_time,
        "max_minus_past_time": max_minus_past_sec,
        "lc": lc_out,
        "lc_time": lc_time,
        "lc_time_past": lc_time_past,
        "lc_res": lc_res,
        "tp": tp_out,
        "tp_time": tp_time,
        "tp_time_past": tp_time_past,
        "tp_res": tp_res,
        "max_plus_all_time": max_plus_all_time,
        "max_plus_time_all_time": max_plus_time_all_time,
        "max_plus_past_time_all_time": max_plus_past_sec_all_time,
        "max_minus_all_time": max_minus_all_time,
        "max_minus_time_all_time": max_minus_time_all_time,
        "max_minus_past_time_all_time": max_minus_past_sec_all_time,
    }


# チェック関数のメイン用(検証と確認を呼び出す）
def check_main(df_r, params):
    """
    受け取ったデータフレームを解析部と結果部に分割し、それぞれの結果をマージする
    :param df_r:
    :return:
    """
    # 各数の定義
    res_part_low = 15  # 結果解析には50行必要(逆順DFでの直近R行が対象の為、[0:R]
    analysis_part_low = 200  # 解析には200行必要(逆順DFで直近N行を結果パートに取られた後の為、[R:R+A])

    # データフレームの切り分け
    # 解析の都合上、１行ラップさせる
    # <検証データ>
    # 2024/1/1 1:35:00
    # 2024/1/1 1:30:00  ←解析トとラップしている行。この行が出来た瞬間（Open）以降は、検証パートの出番。
    # <解析データ＞
    # 2024/1/1 1:30:00   ←この行は通常解析では使わない。2行目の1:25:00が確約した瞬間を取りたいため、足が出来た瞬間を狙うため（Openの瞬間）
    # 2024/1/1 1:25:00   ←事実上の解析開始対象
    # 2024/1/1 1:20:00
    res_part_df = df_r[: res_part_low + 1]  # 終わりは１行ラップさせる
    analysis_part_df = df_r[res_part_low: res_part_low + analysis_part_low]
    # print("　結果照合パート用データ")
    # print(res_part_df.head(2))
    # print(res_part_df.tail(2))
    # print("　解析パート用データ")
    # print(analysis_part_df.head(2))
    # print(analysis_part_df.tail(2))

    # 解析パート　todo
    analysis_result = analysis_part(analysis_part_df, params)  # ana_ans={"ans": bool(結果照合要否必須）, "price": }
    for_export_results = (analysis_result['order_base'] | analysis_result['records'])  # 解析結果を格納
    for_export_results["take_position_flag"] = analysis_result['take_position_flag']
    # 検証パート todo
    if analysis_result['take_position_flag']:  # ポジション判定ある場合のみ
        # 検証と結果の関係性の確認　todo
        conf_ans = confirm_part(res_part_df, analysis_result['order_base'])  # 対象のDataFrame,ポジション取得価格/時刻等,ロスカ/利確幅が必要
        # 検証結果と確認結果の結合
        for_export_results = (for_export_results|conf_ans)

    return for_export_results

def main(params, params_i):
    """
    メイン関数　全てここからスタートする。ここではデータを取得する
    :return:
    """
    global gl_inspection_start_time, gl_inspection_fin_time
    # （０）環境の準備
    # ■■調査用のDFの行数の指定
    res_part_low = 15  # 解析には50行必要(逆順DFでの直近R行が対象の為、[0:R]。check_mainと同値であること。
    analysis_part_low = 200  # 解析には200行必要(逆順DFで直近N行を結果パートに取られた後の為、[R:R+A])。check_mainと同値であること。
    need_analysis_num = res_part_low + analysis_part_low  # 検証パートと結果参照パートの合計。count<=need_analysis_num。
    # ■■取得する足数
    count = gl_count  # 5000
    times = gl_times  # 1  # Count(最大5000件）を何セット取るか
    gr = gl_gr  # "M5"  # 取得する足の単位
    # ■■取得時間の指定
    now_time = gl_now_time  # False  # 現在時刻実行するかどうか False True　　Trueの場合は現在時刻で実行。target_timeを指定したいときはFalseにする。
    target_time = gl_target_time  # datetime.datetime(2024, 3, 13, 16, 20, 6)  # 本当に欲しい時間 (以後ループの有無で調整が入る） 6秒があるため、00:00:06の場合、00:05:00までの足が取れる
    # ■■方法の指定
    inspection_only = gl_inspection_only  # False  # Trueの場合、Inspectionのみの実行（検証等は実行せず）

    # (１)情報の取得
    print('###')
    if now_time:
        # 直近の時間で検証
        df = oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": gr, "count": count}, times)
    else:
        # jp_timeは解析のみは指定時刻のまま、解析＋検証の場合は指定時間を解析時刻となるようにする（検証分を考慮）。
        jp_time = target_time if inspection_only else target_time + datetime.timedelta(minutes=(res_part_low+1)*5)
        euro_time_datetime = jp_time - datetime.timedelta(hours=9)
        euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
        param = {"granularity": gr, "count": count, "to": euro_time_datetime_iso}  # 最低５０行
        df = oa.InstrumentsCandles_multi_exe("USD_JPY", param, times)
        # df = oa.InstrumentsCandles_exe("USD_JPY", param)  # 時間指定
    # データの成型と表示
    df = df["data"]  # data部のみを取得
    df.to_csv(tk.folder_path + 'main_analysis.csv', index=False, encoding="utf-8")  # 直近保存用
    df_r = df.sort_index(ascending=False)  # 逆順に並び替え（直近が上側に来るように）
    # print("全", len(df_r), "行")
    # print(df_r.head(2))
    # print(df_r.tail(2))
    gl_inspection_start_time = df_r.iloc[0]['time_jp']
    gl_inspection_fin_time = df_r.iloc[-1]['time_jp']

    # （2）【解析パートを一回のみ実施する場合】　直近N行で検証パートのテストのみを行う場合はここでTrue
    if inspection_only:
        print("Do Only Inspection　↓解析パート用データ↓")
        print(df_r.head(2))
        analysis_part(df_r[:analysis_part_low])  # 取得したデータ（直近上位順）をそのまま渡す。検証に必要なのは現在200行
        exit()

    # （3）【解析＋検証をセットで行う】連続で実施していく。
    all_ans = []
    print("ループ処理")
    for i in range(len(df_r)):
        print("■", params_i, i, i + need_analysis_num, len(df_r))
        # if i%1000 == 0:
        #     print("■", params_i, i, i + need_analysis_num, len(df_r))
        if i + need_analysis_num <= len(df_r):  # 検証用の行数が確保できていれば,検証へ進む
            ans = check_main(df_r[i: i+need_analysis_num], params)  # ★チェック関数呼び出し
            all_ans.append(ans)
        else:
            print("　終了", i + need_analysis_num, "<=", len(df_r))
            break  # 検証用の行数が確保できない場合は終了

    # （４）結果のまとめ
    print("結果")
    ans_df = pd.DataFrame(all_ans)
    try:
        ans_df.to_csv(tk.folder_path + gl_now_str + 'main_analysis_ans_multi.csv', index=False, encoding="utf-8")
        ans_df.to_csv(tk.folder_path + 'main_analysis_ans_multi_latest.csv', index=False, encoding="utf-8")
    except:
        print("書き込みエラーあり")
        pass


    # 結果の簡易表示用
    print("★★★RESULT★★★")
    print("startTime", gl_start_time)
    fin_time = datetime.datetime.now()
    print("finTime", fin_time)
    print(fin_time - gl_start_time)

    if len(ans_df) == 0:
        print("  対象無し")
        return 0

    fd_forview = ans_df[ans_df["take_position_flag"] == True]  # 取引フラグありのみを抽出
    if len(fd_forview) == 0:
        print("   なにもなし")
        # あんまり書きたくないけど、なんか書かないとエラーになる事が多いんので（値が入ってないとかそういう系の）
        multi_answers.append(
            {"TotalTakePositionFlag": len(fd_forview),
             "TotalTakePosition": 0,
             "tp_times": 0,
             "lc_times": 0,
             "maxPlus": 0,
             "maxMinus": 0,
             "real_plus": 0,
             "real_minus": 0,
             }
        )
        return 0

    print("maxPlus", fd_forview['max_plus'].sum())
    print("maxMinus", fd_forview['max_minus'].sum())
    print("realPlus", fd_forview['tp_res'].sum())
    print("realMinus", fd_forview['lc_res'].sum())
    # 回数
    print("TotalTakePositionFlag", len(fd_forview))
    print("TotalTakePosition", len(fd_forview[fd_forview["position"] == True]))
    print("tpTimes", len(fd_forview[fd_forview["tp"] == True]))
    print("lcTimes", len(fd_forview[fd_forview["lc"] == True]))

    # multi用
    multi_answers.append(
        {"TotalTakePositionFlag": len(fd_forview),
         "TotalTakePosition": len(fd_forview[fd_forview["position"] == True]),
         "tp_times": len(fd_forview[fd_forview["tp"] == True]),
         "lc_times": len(fd_forview[fd_forview["lc"] == True]),
         "maxPlus": fd_forview['max_plus'].sum(),
         "maxMinus": fd_forview['max_minus'].sum(),
         "real_plus": fd_forview['tp_res'].sum(),
         "real_minus":  fd_forview['lc_res'].sum(),
         }
    )


# Mainスタート
params_arr = [  # t_type は順張りか逆張りか。rtはリバーターン、tfはターンフロップを示した単語
    # beforeDoublePeakBreak用
    # {"tf_ratio_max": 0.6, "rt_ratio_min": 0.9, "rt_ratio_max": 1.4, "margin": 0.01, "sl": 1, "d": 1},
    # {"tf_ratio_max": 0.6, "rt_ratio_min": 0.9, "rt_ratio_max": 1.4, "margin": 0.01, "sl": 1, "d": -1},
    # DoublePeak用
    # {"tf_ratio_max": 0.8, "rt_ratio_min": 0.7, "rt_ratio_max": 1.0, "margin": 0.02, "sl": 1, "d": 1},
    # {"tf_ratio_max": 0.8, "rt_ratio_min": 0.7, "rt_ratio_max": 1.0, "margin": 0.02, "sl": 1, "d": -1},
    # {"tf_ratio_max": 0.8, "rt_ratio_min": 0.7, "rt_ratio_max": 1.0, "margin": 0.02, "sl": -1, "d": -1},
    # {"tf_ratio_max": 0.8, "rt_ratio_min": 0.7, "rt_ratio_max": 1.0, "margin": 0.04, "sl": -1, "d": -1},
    # {"tf_ratio_max": 0.5, "rt_ratio_min": 0.4, "rt_ratio_max": 1.0, "margin": 0.03, "sl": 1, "d": 1},
    # {"tf_ratio_max": 0.3, "rt_ratio_min": 0.8, "rt_ratio_max": 1.0, "margin": 0.03, "sl": 1, "d": 1},
    # {"tf_ratio_max": 0.5, "rt_ratio_min": 0.4, "rt_ratio_max": 1.0, "margin": 0.03, "sl": -1, "d": -1},
    # {"tf_ratio_max": 0.3, "rt_ratio_min": 0.8, "rt_ratio_max": 1.0, "margin": 0.03, "sl": -1, "d": -1},
    # DoublePeak4用
    # {"tf_ratio_max": 0.8, "rt_ratio_min": 0.7, "rt_ratio_max": 1.0, "margin": 0.02, "sl": 1, "d": 1, "p": "river"},
    # {"tf_ratio_max": 0.4, "rt_ratio_min": 0.4, "rt_ratio_max": 1.0, "margin": 0.02, "sl": 1, "d": 1, "p": "river"},
    # {"tf_ratio_max": 0.4, "rt_ratio_min": 0.7, "rt_ratio_max": 1.0, "margin": 0.02, "sl": 1, "d": 1, "p": "river"},
    # {"tf_ratio_max": 0.8, "rt_ratio_min": 0.7, "rt_ratio_max": 1.0, "margin": 0.02, "sl": 1, "d": -1, "p": "turn"},
    # {"tf_ratio_max": 0.4, "rt_ratio_min": 0.4, "rt_ratio_max": 1.0, "margin": 0.02, "sl": 1, "d": -1, "p": "turn"},
    # {"tf_ratio_max": 0.4, "rt_ratio_min": 0.7, "rt_ratio_max": 1.0, "margin": 0.02, "sl": 1, "d": -1, "p": "turn"},

    # DoublePeakBreak用
    {"tf_ratio_max": 0.4, "rt_ratio_min": 1.0, "rt_ratio_max": 2, "margin": 0.005, "sl": 1, "d": 1},
    {"tf_ratio_max": 0.4, "rt_ratio_min": 1.0, "rt_ratio_max": 2, "margin": 0.02, "sl": 1, "d": 1},
    {"tf_ratio_max": 0.4, "rt_ratio_min": 1.0, "rt_ratio_max": 2, "margin": 0.005, "sl": -1, "d": -1},
    {"tf_ratio_max": 0.4, "rt_ratio_min": 1.0, "rt_ratio_max": 2, "margin": 0.02, "sl": -1, "d": -1},
    # beforeDoublePeaks用
    # {"tf_ratio": 0.7, "rt_ratio": 0.7, "count": 2, "gap": 0.03, "margin": 0.07, "tg": 0.12, "tc": 7, "tp": 1, "lc": 1, "sl":1 },
    # {"tf_ratio": 0.7, "rt_ratio": 0.7, "count": 2, "gap": 0.03, "margin": 0.03, "tg": 0.12, "tc": 7, "tp": 1, "lc": 1, "sl":1},
    # {"tf_ratio": 0.7, "rt_ratio": 0.7, "count": 2, "gap": 0.03, "margin": 0.03, "tg": 0.12, "tc": 7, "tp": 1, "lc": 1, "sl":-1},
]


# 条件の設定（スマホからいじる時、変更場所の特定が手間なのであえてグローバルで一番下に記載）
gl_count = 5000
gl_times = 3  # Count(最大5000件）を何セット取るか
gl_gr = "M5"  # 取得する足の単位
# ■■取得時間の指定
gl_now_time = False  # 現在時刻実行するかどうか False True　　Trueの場合は現在時刻で実行。target_timeを指定したいときはFalseにする。
gl_target_time = datetime.datetime(2024, 3, 18, 21, 50, 6)  # 検証時間 (以後ループの有無で調整） 6秒があるため、00:00:06の場合、00:05:00までの足が取れる
# ■■方法の指定
gl_inspection_only = False  # Trueの場合、Inspectionのみの実行（検証等は実行せず）
# 開始時間等の取得
gl_inspection_start_time = 0
gl_inspection_fin_time = 0

# メイン実施
multi_answers = []  # 結果一覧を取得
for i in range(len(params_arr)):
    main(params_arr[i], i)

# 終了表示
print("★★★RESULT ALL★★★")
fin_time = datetime.datetime.now()
print("startTime", gl_start_time)
print("finTime", fin_time)
print("検証期間", gl_inspection_start_time, "-", gl_inspection_fin_time)
print("各結果")
for i in range(len(params_arr)):
    print("")
    print("■", params_arr[i])
    print("TotalTakePositionFlag", multi_answers[i]["TotalTakePositionFlag"], "TotalTakePosition", multi_answers[i]["TotalTakePosition"]
          , round((multi_answers[i]["TotalTakePosition"]+0.1)/(multi_answers[i]["TotalTakePositionFlag"]+0.1), 2))
    print("tp_times", multi_answers[i]["tp_times"], "lc_times", multi_answers[i]["lc_times"])
    print("real_plus", multi_answers[i]["real_plus"], "real_minus", multi_answers[i]["real_minus"])
tk.line_send("FIN")