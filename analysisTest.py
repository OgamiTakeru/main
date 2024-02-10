import pandas as pd
import datetime
import fTurnInspection as f  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import making as mk
import fGeneric as f

# グローバルでの宣言
oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義
print(oa.NowPrice_exe("USD_JPY"))
gl_start_time = datetime.datetime.now()


# 解析パート
def analysis_part(df_r):
    print("★★解析パート")
    return mk.turn1Rule(df_r)
    # return mk.now_position(df_r)
    # prac.turn_inspection_main(df_r)


# 確認パート
def confirm_part(df_r, ana_ans):
    print("★★確認パート")
    # 検証パートは古いのから順に並び替える（古いのが↑、新しいのが↓）
    df = df_r.sort_index(ascending=True)  # 逆順に並び替え（直近が上側に来るように）
    df = df[:10]
    confirm_start_price = df.iloc[0]['open']
    print("検証開始価格", confirm_start_price)

    # 設定 (150スタート、方向1の場合、DFを巡回して150以上どのくらい行くか)
    trigger_price = ana_ans['trigger_price']  # 検証の基準の価格
    start_time = df.iloc[0]['time_jp']
    expect_direction = ana_ans['expect_direction']  # 進むと予想した方向(1の場合high方向がプラス。
    lc_r = ana_ans['lc_range']  # ロスカの幅（正の値）
    tp_r = ana_ans['tp_range']  # 利確の幅（正の値）

    # 即時のポジションかを判定する
    if confirm_start_price - 0.03 < trigger_price < confirm_start_price + 0.03:
        print(" 即時ポジション", trigger_price, expect_direction)
        position_price = trigger_price
        position_time = df.iloc[0]['time_jp']
        position = True
    else:
        print(" ポジション取得待ち", trigger_price, expect_direction)
        position_price = 0  # 念のため。。
        position = False
        position_time = 0

    # 検証する
    max_upper = 0
    max_lower = 0
    lc_out = False
    tp_out = False
    max_upper_time = 0
    max_upper_past_sec = 0
    max_lower_time = 0
    max_lower_past_sec = 0
    lc_time = 0
    lc_time_past = 0
    lc_res = 0
    tp_time = 0
    tp_time_past = 0
    tp_res = 0
    for i, item in df.iterrows():
        if position:
            # ■　ポジションがある場合の処理
            # スタートよりも最高値が高い場合、それはプラス域。逆にマイナス域分も求めておく
            upper = item['high'] - position_price if position_price < item['high'] else 0
            lower = position_price - item['low'] if position_price > item['low'] else 0
            if upper > max_upper:
                max_upper = upper
                max_upper_time = item['time_jp']
                max_upper_past_sec = f.seek_time_gap_seconds(item['time_jp'], start_time)

            if lower > max_lower:
                max_lower = lower
                max_lower_time = item['time_jp']
                max_lower_past_sec = f.seek_time_gap_seconds(item['time_jp'], start_time)

            # ロスカ分を検討する
            if lc_r != 0:  # ロスカ設定ありの場合、ロスカに引っかかるかを検討
                lc_jd = lower if expect_direction == 1 else upper  # 方向が買(expect=1)の場合、LCはLower方向。
                if lc_jd > lc_r:  # ロスカが成立する場合
                    print(" 　LC★", item['time_jp'], lc_r)
                    lc_out = True
                    lc_time = item['time_jp']
                    lc_time_past = f.seek_time_gap_seconds(item['time_jp'], start_time)
                    lc_res = lc_r
            if tp_r != 0:  # TP設定あるの場合、利確に引っかかるかを検討
                tp_jd = upper if expect_direction == 1 else lower  # 方向が買(expect=1)の場合、LCはLower方向。
                if tp_jd > tp_r:
                    print(" 　TP★", item['time_jp'], tp_r)
                    tp_out = True
                    tp_time = item['time_jp']
                    tp_time_past = f.seek_time_gap_seconds(item['time_jp'], start_time)
                    tp_res = tp_r
            # ループの終了判定
            if lc_out or tp_out:
                break
        else:
            # ■ポジションがない場合の動き(ポジションを取得する）
            if item['low'] < trigger_price < item['high']:
                position = True
                position_price = trigger_price
                print(" 　取得★", item['time_jp'], position_price)

    # 情報整理＠ループ終了後（マイナス方向の整理）
    if expect_direction == 1:  # 買い方向を想定した場合
        max_minus = round(max_lower, 3)
        max_minus_time = max_lower_time
        max_minus_past_sec = max_lower_past_sec
        max_plus = round(max_upper, 3)
        max_plus_time = max_upper_time
        max_plus_past_sec = max_upper_past_sec
    else:
        max_minus = round(max_upper, 3)
        max_minus_time = max_upper_time
        max_minus_past_sec = max_upper_past_sec
        max_plus = round(max_lower, 3)
        max_plus_time = max_lower_time
        max_plus_past_sec = max_lower_past_sec

    print("買い方向", expect_direction, "最大プラス",max_plus, max_plus_time,  "最大マイナス", max_minus, max_minus_time)

    return {
        "position": position,
        "position_time": position_time,
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
        "tp_res":tp_res
    }


# チェック関数のメイン用(検証と確認を呼び出す）
def check_main(df_r):
    """
    受け取ったデータフレームを解析部と結果部に分割し、それぞれの結果をマージする
    :param df_r:
    :return:
    """
    # 各数の定義
    res_part_low = 15  # 結果解析には50行必要(逆順DFでの直近R行が対象の為、[0:R]
    analysis_part_low = 200  # 解析には200行必要(逆順DFで直近N行を結果パートに取られた後の為、[R:R+A])

    # データフレームの切り分け
    res_part_df = df_r[: res_part_low]
    analysis_part_df = df_r[res_part_low: res_part_low + analysis_part_low]
    print("　結果照合パート用データ")
    print(res_part_df.head(2))
    print(res_part_df.tail(2))
    print("　解析パート用データ")
    print(analysis_part_df.head(2))
    print(analysis_part_df.tail(2))

    # 検証パート　todo
    ana_ans = analysis_part(analysis_part_df)  # ana_ans={"ans": bool(結果照合要否必須）, "price": }
    # 結果照合パート todo
    if ana_ans['ans']:  # ポジション判定ある場合のみ
        # 検証と結果の関係性の確認　todo
        conf_ans = confirm_part(res_part_df, ana_ans)
        # 検証結果と確認結果の結合
        ana_ans = dict(**ana_ans, **conf_ans)
    return ana_ans


def main():
    """
    メイン関数　全てここからスタートする。ここではデータを取得する
    :return:
    """
    # （０）環境の準備
    # ■■調査用のDFの行数の指定
    res_part_low = 15  # 解析には50行必要(逆順DFでの直近R行が対象の為、[0:R]。check_mainと同値であること。
    analysis_part_low = 200  # 解析には200行必要(逆順DFで直近N行を結果パートに取られた後の為、[R:R+A])。check_mainと同値であること。
    need_analysis_num = res_part_low + analysis_part_low  # 検証パートと結果参照パートの合計。count<=need_analysis_num。
    # ■■取得する足数
    count = 4000
    # count = need_analysis_num + 1  # need_analysis_num + 1  # 取得する行数。単発実行の場合はこの数で調整⇒ need_analysis_num + 1
    times = 1# Count(最大5000件）を何セット取るか
    # ■■取得時間の指定
    now_time =True  # 現在時刻実行するかどうか False True
    target_time = datetime.datetime(2023, 12, 29, 16, 50, 6)  # 本当に欲しい時間 (以後ループの有無で調整が入る）
    gr = "M5"
    # ■■方法の指定
    inspection_only = False  # Trueの場合、Inspectionのみの実行（検証等は実行せず）

    # (１)情報の取得
    print('###')
    if now_time:
        # 直近の時間で検証
        df = oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": gr, "count": count}, times)
    else:
        # jp_timeは解析のみはダイレクト、解析＋検証の場合は検証の時間を考慮(検証分を後だしした時刻)して解析を取得する。
        jp_time = target_time if inspection_only else target_time + datetime.timedelta(minutes=(res_part_low+1)*5)
        euro_time_datetime = jp_time - datetime.timedelta(hours=9)
        euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
        param = {"granularity": gr, "count": count, "to": euro_time_datetime_iso}  # 最低５０行
        df = oa.InstrumentsCandles_multi_exe("USD_JPY", param, times)
        # df = oa.InstrumentsCandles_exe("USD_JPY", param)  # 時間指定
    # データの成型と表示
    df = df["data"]  # data部のみを取得
    df.to_csv(tk.folder_path + 'analisysTEST.csv', index=False, encoding="utf-8")  # 直近保存用
    df_r = df.sort_index(ascending=False)  # 逆順に並び替え（直近が上側に来るように）
    print("全", len(df_r), "行")
    print(df_r.head(2))
    print(df_r.tail(2))

    # （2）単発調査用！！　直近N行で検証パートのテストの実を行う場合はここでTrue
    if inspection_only:
        print("Do Only Inspection　↓解析パート用データ↓")
        print(df_r.head(2))
        analysis_part(df_r[:analysis_part_low])  # 取得したデータ（直近上位順）をそのまま渡す。検証に必要なのは現在200行
        exit()

    # （3）連続検証データを渡していく（ループ　or 単発）
    all_ans = []
    print("ループ処理")
    for i in range(len(df_r)):
        print("■", i, i + need_analysis_num, len(df_r))
        if i + need_analysis_num <= len(df_r):  # 検証用の行数が確保できていれば,検証へ進む
            ans = check_main(df_r[i: i+need_analysis_num])  # ★チェック関数呼び出し
            all_ans.append(ans)
        else:
            print("　終了",i + need_analysis_num, "<=", len(df_r))
            break  # 検証用の行数が確保できない場合は終了

    # （４）結果のまとめ
    print("結果")
    ans_df = pd.DataFrame(all_ans)
    ans_df.to_csv(tk.folder_path + 'inspection.csv', index=False, encoding="utf-8")  # 直近保存用

    # 結果の簡易表示用
    print("★★★RESULT★★★")
    fin_time = datetime.datetime.now()
    fd_forview = ans_df[ans_df["ans"] == True]  # 取引有のみを抽出
    if len(fd_forview) == 0:
        return 0
    print("startTime", gl_start_time)
    print("finTime", fin_time)

    print("maxPlus", fd_forview['max_plus'].sum())
    print("maxMinus", fd_forview['max_minus'].sum())
    print("realPlus", fd_forview['tp_res'].sum())
    print("realMinus", fd_forview['lc_res'].sum())
    # 回数
    print("TotalTimes", len(fd_forview))
    print("tpTimes", len(fd_forview[fd_forview["tp"] == True]))
    print("lcTimes", len(fd_forview[fd_forview["lc"] == True]))

# Mainスタート
main()


