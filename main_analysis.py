import pandas as pd
import datetime
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import fInspection_order_Main as im
import fGeneric as gene
import fResistanceLineInspection as ri
import fDoublePeaks as dp
import fMoveSizeInspection as ms
import math

# グローバルでの宣言
oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義
print(oa.NowPrice_exe("USD_JPY"))
gl_start_time = datetime.datetime.now()
gl_now = datetime.datetime.now().replace(microsecond=0)  # 現在の時刻を取得
gl_now_str = str(gl_now.month).zfill(2) + str(gl_now.day).zfill(2) + "_" + \
            str(gl_now.hour).zfill(2) + str(gl_now.minute).zfill(2) + "_" + str(gl_now.second).zfill(2)

# 解析パート
def analysis_part(df_r):
    """
    この解析パートでは、ポジションを持つかのフラグを含めた、ポジションに必要な情報を返却する
    必須項目は以下の通り。
    "take_position_flag": take_position_flag,  # ポジション取得指示あり
    "decision_time": df_r_part.iloc[0]['time_jp'],  # 直近の時刻（ポジションの取得有無は無関係）
    "decision_price": df_r_part.iloc[0]['open'],  # ポジションフラグ成立時の価格（先頭[0]列のOpen価格）
    "position_margin": peak_river['gap'] * -1,  # position_margin,  #
    "lc_range": peak_turn['gap'], # 0.04,  # ロスカットレンジ（ポジションの取得有無は無関係）
    "tp_range": peak_turn['gap'], #0.06,  # 利確レンジ（ポジションの取得有無は無関係）
    "expect_direction": peak_turn['direction'] * -1,  # ターン部分の方向
    :param df_r:
    :return:
        "oeder_base"が必須
    """
    # モードによる引数の差分を処理
    # ans = ms.cal_move_size(df_r)
    # ans = im.inspection_predict_line_make_order(df_r)
    ans = im.inspection_warp_up_and_make_order(df_r)

    print("最終（main_analysis)")
    print(ans)
    oa.OrderCreate_dic_support(ans['exe_orders'][0])
    return ans

    # ダブルトップは特殊
    # test = dp.DoublePeak({"df_r": df_r})
    # print(test)
    # return test

# 検証パート
def confirm_part(df_r, order):
    """

    :param df_r: 検証用のデータフレーム（関数内で5S足のデータを別途取得する場合は利用しない）
    :param order: 解析の結果、どの価格でポジションを取得するか等の情報を「辞書形式」で（単品）
    ana_ans = exe_order = {
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
    # ここはパラメータを受け取らないため、通常検証かループ検証かの影響を受けない
    print("■　確認パート")
    # 検証パートは古いのから順に並び替える（古いのが↑、新しいのが↓）
    df = df_r.sort_index(ascending=True)  # 正順に並び替え（古い時刻から新しい時刻に向けて１行づつ検証する）
    df = df[:10]
    confirm_start_time = df.iloc[0]['time']  # 検証開始時間を入れる
    # 検証用の５秒足データを取得し、荒い足のdfに上書きをする（上書きにすることで、この部分をコメントアウトすれば変数名を変えなくても対応可能）
    params = {
        "granularity": "S5",
        "count": 720,  # 約45分= 5秒足×550足分  , 60分　= 720
        "from": confirm_start_time,
    }
    df = oa.InstrumentsCandles_multi_exe("USD_JPY", params, 1)['data']
    print(" 検証対象")
    print(df.head(2))
    print(df.tail(2))

    # ★設定　基本的に解析パートから持ってくる。 (150スタート、方向1の場合、DFを巡回して150以上どのくらい行くか)
    position_target_price = order['target_price']  # マージンを考慮
    start_time = df.iloc[0]['time_jp']  # ポジション取得決心時間（正確には、５分後）
    expected_direction = order['expected_direction']  # 進むと予想した方向(1の場合high方向がプラス。
    lc_range = order['lc_range']  # ロスカの幅（正の値）
    tp_range = order['tp_range']  # 利確の幅（正の値）

    # 即時のポジションかを判定する
    if df.iloc[0]['open'] - 0.008 < position_target_price < df.iloc[0]['open'] + 0.008:  # 多少の誤差（0.01)は即時ポジション。マージンがない場合は基本即時となる。
        print(" 即時ポジション", position_target_price, expected_direction)
        position_time = df.iloc[0]['time_jp']
        position = True
    else:
        print(" ポジション取得待ち", position_target_price, expected_direction)
        position_time = 0
        position = False

    # 検証する
    max_plus = 0
    max_minus = 0
    max_plus_time = 0
    max_plus_past_sec = 0
    max_minus_time = 0
    max_minus_past_sec = 0
    lc_executed = False
    tp_executed = False
    lc_time = 0
    lc_time_past = 0
    lc_res = 0
    tp_time = 0
    tp_time_past = 0
    tp_res = 0
    max_plus_all_time = 0
    max_minus_all_time = 0
    max_plus_time_all_time = 0
    max_plus_past_sec_all_time = 0
    max_minus_time_all_time = 0
    max_minus_past_sec_all_time = 0
    end_time_of_inspection = 0
    pl = 0
    pl_tp_lc_include = 0
    for i, item in df.iterrows():
        if position:
            # ■　ポジションがある場合の処理
            # ①-1 共通
            end_time_of_inspection = item['time_jp']  # 最後に検証した時刻を、検証終了時刻として保管（ループを全て行う場合）
            # ①-2 プラス、マイナスに変換する（ポジションの方向ごとに異なる）
            if expected_direction == 1:
                # 買い方向の場合
                plus = item['high'] - position_target_price
                minus = (position_target_price - item['low']) * -1  # 負の値で表現
            else:
                # 売りの方向の場合
                plus = position_target_price - item['low']
                minus = (item['high'] - position_target_price) * -1  # 負の値で表現
            # ①-3 全区間で調査する項目を調査する（TP/LC後でも関係なく更新していく）
            if plus > max_plus_all_time:
                # 全区間でPlusを更新する場合、記録する
                max_plus_all_time = plus
                max_plus_time_all_time = item['time_jp']
                max_plus_past_sec_all_time = gene.seek_time_gap_seconds(item['time_jp'], start_time)
            elif abs(minus) > abs(max_minus_all_time):
                # 全区間でminusを更新する場合、記録する
                max_minus_all_time = minus  # 最小値入れ替え
                max_minus_time_all_time = item['time_jp']
                max_minus_past_sec_all_time = gene.seek_time_gap_seconds(item['time_jp'], start_time)

            # ■■通常のPositionの管理。Positionがあり、TPやLCがない、通常のポジション状態を記録していく
            if not lc_executed and not tp_executed:
                # ■■■情報を更新する
                if plus > max_plus:
                    # 全区間でPlusを更新する場合、記録する
                    max_plus = plus
                    max_plus_time = item['time_jp']
                    max_plus_past_sec = gene.seek_time_gap_seconds(item['time_jp'], start_time)
                elif abs(minus) > abs(max_minus):
                    # 全区間でminusを更新する場合、記録する
                    max_minus = minus  # 最小値入れ替え
                    max_minus_time = item['time_jp']
                    max_minus_past_sec = gene.seek_time_gap_seconds(item['time_jp'], start_time)
                # ■■■PLを更新する（これはポジション所持中のみの実行）
                if expected_direction == 1:
                    # 買い方向の場合
                    pl = item['close'] - position_target_price  # 足クローズ時点の含み損益（損はマイナス値、益はプラス値）
                    pl_tp_lc_include = pl  # 暫定的に入れておく（この足でTP/LCに当たった場合は、後でTPに差し替える）
                else:
                    # 売りの方向の場合
                    pl = position_target_price - item['close']  # 足クローズ時点の含み損益（損はマイナス値、益はプラス値）
                    pl_tp_lc_include = pl  # 暫定的に入れておく（この足でTP/LCに当たった場合は、後でTPに差し替える）
                # ■■■TP/LCを判定する　position_flag はtrueを維持する（TP.LC後もFalseには変更しない）
                if lc_range != 0:  # ロスカ設定ありの場合、ロスカに引っかかるかを検討
                    if abs(minus) > lc_range:  # ロスカが成立する場合(lc_rangeは正の数で指定されているのでabs不要)
                        print(" 　LC★", item['time_jp'], lc_range)
                        lc_executed = True
                        lc_time = item['time_jp']
                        lc_time_past = gene.seek_time_gap_seconds(item['time_jp'], start_time)
                        lc_res = lc_range
                        pl_tp_lc_include = lc_range * -1  # LCにかかった瞬間を取るため。（pcは正負で考慮するため、lc_rangeは*-1)
                if tp_range != 0:  # TP設定あるの場合、利確に引っかかるかを検討
                    if plus > tp_range:
                        if lc_executed:
                            # LC成立時は何もしない（LCの数字を優先し、TPを入力しない）
                            pass
                        else:
                            # LCが成立してなければ、TPを成立させる
                            print(" 　TP★", item['time_jp'], tp_range)
                            tp_executed = True
                            tp_time = item['time_jp']
                            tp_time_past = gene.seek_time_gap_seconds(item['time_jp'], start_time)
                            tp_res = tp_range
                            pl_tp_lc_include = tp_range  # LCにかかった瞬間を取るため。
        else:
            # ■ポジションがない場合の動き(ポジションを取得する）
            if item['low'] < position_target_price < item['high']:
                position = True  # 集計に利用するため、一度TrueにしたらFalseにはしないようにする
                position_time = item['time_jp']
                print(" 　取得★", item['time_jp'], position_target_price)

    print("   買い方向", expected_direction, "最大プラス", max_plus, max_plus_time,  "最大マイナス", max_minus, max_minus_time)

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
        "lc": lc_executed,
        "lc_time": lc_time,
        "lc_time_past": lc_time_past,
        "lc_res": lc_res,
        "tp": tp_executed,
        "tp_time": tp_time,
        "tp_time_past": tp_time_past,
        "tp_res": tp_res,
        "max_plus_all_time": max_plus_all_time,
        "max_plus_time_all_time": max_plus_time_all_time,
        "max_plus_past_time_all_time": max_plus_past_sec_all_time,
        "max_minus_all_time": max_minus_all_time,
        "max_minus_time_all_time": max_minus_time_all_time,
        "max_minus_past_time_all_time": max_minus_past_sec_all_time,
        "pl": pl,  # TPやLCに至らない場合でも、検証区間の最終Closeでプラスかマイナスかを取得する
        "pl_tp_lc_include": pl_tp_lc_include  # PLは変動分なので従来TPやLCは考慮しないが、考慮した分も取得しておく
    }


# チェック関数のメイン用(検証と確認を呼び出す）
def inspection_and_confirm(df_r, i):
    """
    ・第二期引数には、今何回目の処理かを受け取る（何回目かを表示したかったため）
    ・この関数は、解析と検証をセットで行う場合に呼び出される（解析のみの場合は、別の関数を利用する）
    ・受け取ったデータフレームを解析部と結果部に分割し、それぞれの結果をマージし、CSVに吐き出す。
    　そのCSV作成時は、FlagがFalseについてもデータを残す仕様にしているため、
    　FlagがFalseであっても、InspectionMain(解析側から）オーダーベースは必ず返却してもらう必要がある。
    :param df_r:    通常の解析と、ループの解析で利用する。
    【検証と解析の境目は以下の通り】
        # データフレームの切り分け
        # 解析の都合上、１行ラップさせる
        # <検証データ>
        # 2024/1/1 1:35:00
        # 2024/1/1 1:30:00  ←解析トとラップしている行。この行が出来た瞬間（Open）以降は、検証パートの出番。
        # <解析データ＞
        # 2024/1/1 1:30:00   ←この行は通常解析では使わない。2行目の1:25:00が確約した瞬間を取りたいため、足が出来た瞬間を狙うため（Openの瞬間）
        # 2024/1/1 1:25:00   ←事実上の解析開始対象
        # 2024/1/1 1:20:00
    【検証で必要なもの】

    :return:
    """
    # 各数の定義
    global gl_inspection_start_time, gl_inspection_end_time
    res_part_low = gl_res_part_low + 1  # 結果解析には50行必要(逆順DFでの直近R行が対象の為、[0:R]  必要な行が２５行なら、＋１のあたい（２６とする）
    analysis_part_low = gl_analysis_part_low  # 解析には200行必要(逆順DFで直近N行を結果パートに取られた後の為、[R:R+A])
    res_part_df = df_r[: res_part_low + 1]  # 終わりは１行ラップさせる(理由は上記で説明）
    analysis_part_df = df_r[res_part_low: res_part_low + analysis_part_low]
    print("　結果照合パート用データ")
    print(res_part_df.head(2))
    print(res_part_df.tail(2))
    print("　解析パート用データ")
    print(analysis_part_df.head(2))
    print(analysis_part_df.tail(2))

    #■ 検証の開始時刻（データ上）と終了時刻を保存しておく（表示用）
    print(i ,"i")
    if i == 0:
        print(" 初回")
        gl_inspection_start_time = analysis_part_df.iloc[0]['time_jp']
    else:
        print("　それ以外")
        gl_inspection_end_time = analysis_part_df.iloc[0]['time_jp']

    # ■解析パート　todo
    analysis_result = analysis_part(analysis_part_df)  # ana_ans={"ans": bool(結果照合要否必須）, "price": }
    print(analysis_result)
    for_export_results = analysis_result['exe_order'] # (analysis_result['order_base'] | analysis_result['records'])  # 解析結果を格納
    for_export_results["take_position_flag"] = analysis_result['take_position_flag']
    # ■検証パート todo
    if analysis_result['take_position_flag']:  # ポジション判定ある場合のみ
        # 検証と結果の関係性の確認　todo
        conf_ans = confirm_part(res_part_df, analysis_result['exe_order'])  # 対象のDataFrame,ポジション取得価格単品/時刻等,ロスカ/利確幅が必要
        # 検証結果と確認結果の結合
        for_export_results = (for_export_results|conf_ans)

    return for_export_results


def main():
    """
    メイン関数　全てここからスタートする。ここではデータを取得する
    通常の解析と、ループの解析で利用する。
    通常の解析の場合、*argsは０個。
    ループ解析(別ファイルの関数)の場合、*argsはargs[0]はparams(パラメータ集)、dic_args[1]はパメータ番号(表示用）
    :return:
    """

    # （０）環境の準備
    mode = "2time"
    f = 5
    # if gl_inspection_only:
    #     # 指定の時刻を起点に、調査のみを行うデータ
    #     if gl_use_now:
    #         # 直近の時間で検証
    #         df = oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": gr, "count": count}, 1)
    #     else:
    #         # jp_timeは解析のみは指定時刻のまま、解析＋検証の場合は指定時間を解析時刻となるようにする（検証分を考慮）。
    #         euro_time_datetime_iso = str((gl_target_time - datetime.timedelta(hours=9)).isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
    #         param = {"granularity": gl_gr, "count": gl_analysis_part_low, "to": euro_time_datetime_iso}  # 最低５０行
    #         df = oa.InstrumentsCandles_multi_exe("USD_JPY", param, 1)
    # elif mode == "1time":
    #     # 調査＋検証を行う場合（target_timeから時系列的に前方向に、調査を進めていく)
    #     # 指定の時刻を起点に、調査のみを行うデータ
    #     if gl_use_now:
    #         # 直近の時間で検証
    #         df = oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": gr, "count": count}, 1)
    #     else:
    #         # jp_timeは解析のみは指定時刻のまま、解析＋検証の場合は指定時間を解析時刻となるようにする（検証分を考慮）。
    #         # 調査区間85足、検証区間25足の場合、トータルでは(85+25-1)足必要となる。(検証時刻の1行が重複するため。他細かいとこは無視！）
    #         # countではなく時刻で直接的に指定する（5000を超える場合はも時間差で検討）
    #         inspection_from = gene.time_to_euro_iso(gl_target_time - datetime.timedelta(minutes=f * gl_analysis_part_low))
    #         inspection_to = gene.time_to_euro_iso(gl_target_time)  # 基準
    #         confirm_from = gene.time_to_euro_iso(gl_target_time)
    #         confirm_to = gene.time_to_euro_iso(gl_target_time +  datetime.timedelta(minutes=f * gl_res_part_low))
    #         print(" 計算上の必要足数", gene.seek_time_gap_seconds(inspection_from,confirm_to)/60/f)
    #         print(" 時間", gl_target_time - datetime.timedelta(minutes=f * gl_analysis_part_low),
    #               gl_target_time +  datetime.timedelta(minutes=f * gl_res_part_low))
    #         param = {"granularity": gl_gr, "from": inspection_from, "to": confirm_to}
    #         df_inspection = oa.InstrumentsCandles_multi_exe("USD_JPY", param, 1)['data']
    #         print(" 実際の足数", len(df_inspection))
    #         print(df_inspection)
    # else:

    # print(" test", gl_target_time)
    # # 大量のデータでテストする(指定方法は、指定日時を最後の調査＋検証の対象とする。500回調査の場合、それより前500足分スライド）
    # param = {"granularity": "M5", "count":20, "to": gene.time_to_euro_iso(gl_target_time)}
    # all_m5_data = oa.InstrumentsCandles_multi_exe("USD_JPY", param, 1)['data']
    # print("@")
    #
    # # 全データの開始時間
    # count_max = 500
    # all_m5_data_from_time = all_m5_data.iloc[0]['time_jp']
    # all_m5_data_to_time = all_m5_data.iloc[-1]['time_jp']
    # print(" データの最初の時刻は", all_m5_data_from_time, "最後の時刻", all_m5_data_to_time)
    # gap_second = gene.seek_time_gap_seconds(all_m5_data_from_time, all_m5_data_to_time)
    # additional_second = gl_res_part_low * 5 * 60
    # print(" 検証に必要な秒数", additional_second, additional_second /60/ 5)
    # need_foot = gap_second / 5 #  (gap_second + additional_second) / 5
    # print(" 時間差", gap_second, gap_second / 60, "分", ",foot数", need_foot)
    # need_api_count_float = need_foot / count_max
    # need_api_count = math.ceil(need_api_count_float)
    # print(" 正確ループ数", need_api_count_float, "切り上げたループ数", need_api_count)
    # params_s5 = {"granularity": "S5", "count":count_max, "to": gene.time_to_euro_iso(gene.str_to_time(all_m5_data_from_time))}
    # all_s5_data = oa.InstrumentsCandles_multi_exe("USD_JPY", params_s5, need_api_count)
    #
    #
    #
    # print(" 必要な足数", need_foot, "必要な繰り返し数(小数点)", need_api_count_float, "必要な繰り返し数(切り上げ)", need_api_count)
    #
    #
    # print(" データ確認します")
    # print(all_m5_data)
    # print(" 5秒足")
    # print(all_s5_data)
    #
    #



    # ■■調査用のDFの行数の指定
    res_part_low = gl_res_part_low  # 解析には50行必要(逆順DFでの直近R行が対象の為、[0:R]。check_mainと同値であること。
    analysis_part_low = gl_analysis_part_low  # 解析には200行必要(逆順DFで直近N行を結果パートに取られた後の為、[R:R+A])。check_mainと同値であること。
    need_analysis_num = res_part_low + analysis_part_low  # 検証パートと結果参照パートの合計。count<=need_analysis_num。
    # ■■取得する足数
    count = gl_count  # 5000
    times = gl_times  # 1  # Count(最大5000件）を何セット取るか
    gr = gl_gr  # "M5"  # 取得する足の単位
    # ■■取得時間の指定
    now_time = gl_use_now  # False  # 現在時刻実行するかどうか False True　　Trueの場合は現在時刻で実行。target_timeを指定したいときはFalseにする。
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
    df.to_csv(tk.folder_path + 'main_analysis_original_data.csv', index=False, encoding="utf-8")  # 直近保存用
    df_r = df.sort_index(ascending=False)  # 逆順に並び替え（直近が上側に来るように）
    print("全", len(df_r), "行")
    print(df_r.head(2))
    print(df_r.tail(2))

    # （2）【解析パートを一回のみ実施する場合】　直近N行で検証パートのテストのみを行う場合はここでTrue
    if inspection_only:
        print("Do Only Inspection　↓解析パート用データ↓")
        print(df_r.head(2))
        analysis_part(df_r[:analysis_part_low])  # 取得したデータ（直近上位順）をそのまま渡す。検証に必要なのは現在200行
        exit()

    # （3）【解析＋検証をセットで行う】を実施する
    # jp_time = target_time if inspection_only else target_time + datetime.timedelta(minutes=(res_part_low + 1) * 5)
    # euro_time_datetime = target_time - datetime.timedelta(hours=9)
    # euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
    # 確認範囲を取得する(確認範囲は、
    euro_time_datetime_iso = str((target_time - datetime.timedelta(hours=9)).isoformat()) + ".000000000Z"
    params = {
        "granularity": "M5",
        "count": 25,  # 約45分= 5秒足×550足分  , 60分　= 720
        "from": euro_time_datetime_iso,
    }
    df = oa.InstrumentsCandles_multi_exe("USD_JPY", param, times)
    print(" 確認範囲",)
    print(df)



    all_ans = []
    print("ループ処理")
    for i in range(len(df_r)):
        print("■■■■■■■■■■■■", i, i + need_analysis_num, len(df_r))
        # 処理開始
        if i + need_analysis_num <= len(df_r):  # 検証用の行数が確保できていれば,検証へ進む
            ans = inspection_and_confirm(df_r[i: i + need_analysis_num], i)  # ★チェック関数呼び出し
            all_ans.append(ans)
        else:
            print("　終了", i + need_analysis_num, "<=", len(df_r))
            break  # 検証用の行数が確保できない場合は終了

    # （４）結果のまとめ
    print("結果")
    ans_df = pd.DataFrame(all_ans)
    try:
        ans_df.to_csv(tk.folder_path + gl_now_str + 'main_analysis_ans.csv', index=False, encoding="utf-8")
        ans_df.to_csv(tk.folder_path + 'main_analysis_ans_latest.csv', index=False, encoding="utf-8")
    except:
        print("書き込みエラーあり")
        pass


    # 結果の簡易表示用
    tk.line_send("■■inspection fin", )  # LINEは先に送っておく（ログの最終行に表示されないように、先に表示）
    print("★★★RESULT★★★")
    fin_time = datetime.datetime.now()
    fd_forview = ans_df[ans_df["take_position_flag"] == True]  # 取引有のみを抽出
    if len(fd_forview) == 0:
        return 0

    print("maxPlus", fd_forview['max_plus'].sum(), "maxMinus", fd_forview['max_minus'].sum())
    print("realTP_Plus", fd_forview['tp_res'].sum(), "realLC_Minus", fd_forview['lc_res'].sum())
    # 回数
    print("startTime", gl_start_time , "finTime", fin_time)
    print("TakePositionFlag", len(fd_forview), "TakePosition", len(fd_forview[fd_forview["position"] == True]))
    print("tpTimes", len(fd_forview[fd_forview["tp"] == True]),"lcTimes", len(fd_forview[fd_forview["lc"] == True]))
    print("realAllPL",  round(fd_forview['pl'].sum(), 3),
          "realAllPL_includeTPLC", round(fd_forview['pl_tp_lc_include'].sum(), 3))

    print("検証期間", gl_inspection_end_time, "-", gl_inspection_start_time)

# 条件の設定（スマホからいじる時、変更場所の特定が手間なのであえてグローバルで一番下に記載）
# datetime.datetime(2024, 8, 10, 0, 15, 6)  # テスト用（ダブルトップあり）
# datetime.datetime(2024, 4, 1, 12, 45, 6)←ダブルトップ！
# datetime.datetime(2023, 8, 6, 16, 35, 6) 結構負ける時間　
# datetime.datetime(2024, 8, 9, 23, 55, 6) # 予測テスト用
gl_gr = "M5"  # 取得する足の単位
gl_inspection_start_time = 0
gl_inspection_end_time = 0

# 解析と検証に必要な行数
gl_res_part_low = 25  # 解析には50行必要(逆順DFでの直近R行が対象の為、[0:R]。check_mainと同値であること。
gl_analysis_part_low = 85  # 解析には200行必要(逆順DFで直近N行を結果パートに取られた後の為、[R:R+A])。check_mainと同値であること。
# 取得する行数(1回のテストをしたい場合、指定でもres_part_low + analysis_part_lowが必要）
gl_count = gl_res_part_low + gl_analysis_part_low + 1
gl_times = 1  # Count(最大5000件）を何セット取るか  大体2225×３で１か月位。　10時間は120足 1時間は12
# ■■取得時間の指定
gl_use_now = False  # 現在時刻実行するかどうか False True　　Trueの場合は現在時刻で実行。target_timeを指定したいときはFalseにする。
gl_target_time = datetime.datetime(2024, 9, 27, 22, 5, 6)  # 検証時間 (以後ループの有無で調整） 6秒があるため、00:00:06の場合、00:05:00までの足が取れる
# ■■方法の指定
gl_inspection_only = True  # Trueの場合、Inspectionのみの実行（検証等は実行せず）。検証は上記指定を先頭にし、古い時間方向へ調査していく。
# gl_inspection_only = False  # Trueの場合、Inspectionのみの実行（検証等は実行せず）。検証は上記指定を先頭にし、古い時間方向へ調査していく。

# Mainスタート
main()