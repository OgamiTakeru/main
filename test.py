import pandas as pd
import datetime
import fTurnInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import making as mk
import fGeneric as f

# グローバルでの宣言
oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義
print(oa.NowPrice_exe("USD_JPY"))
gl_start_time = datetime.datetime.now()


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
    count = 220
    gr = "M5"  # 取得する足の単位
    times = 1# Count(最大5000件）を何セット取るか
    # ■■取得時間の指定
    now_time = False  # 現在時刻実行するかどうか False True　　Trueの場合は現在時刻で実行。target_timeを指定したいときはFalseにする。
    target_time = datetime.datetime(2024, 2, 15, 16, 5, 6)  # 本当に欲しい時間 (以後ループの有無で調整が入る）
    # ■■方法の指定
    inspection_only = True  # Trueの場合、Inspectionのみの実行（検証等は実行せず）

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
    print("全", len(df_r), "行")
    print(df_r.head(2))
    print(df_r.tail(2))

    df_r_part = df_r[:90]  # 検証に必要な分だけ抜き取る
    peaks_info =t.turn_each_inspection(df_r_part)
    print(peaks_info)

# Mainスタート
main()


