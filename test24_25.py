import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import datetime
import fAnalysis_order_Main as im
import classInspection as ci
import fTurnInspection as pi

memo = "少量24_25 "
func = im.wrap_all_inspections
# func = im.analysis_old_flag

loop = [
    datetime.datetime(2024, 10, 3, 9, 25, 0),  # いいマイナスデータ
    # datetime.datetime(2024, 10, 10, 9, 25, 0),  # いいマイナスデータ
    datetime.datetime(2023, 9, 23, 23, 40, 6),  # Break系のいいマイナスデータ
    # datetime.datetime(2023, 3, 6, 23, 40, 6),  # いいマイナスデータ
    datetime.datetime(2022, 2, 6, 23, 40, 6),  # いいマイナスデータ
]
# mode = 1
mode = 2
mode = 3

if mode == 1:
    intest = ci.Inspection(pi.wrap_predict_turn_inspection_test,
                           False,
                           # datetime.datetime(2024, 10, 3, 9, 25, 0),  # いいマイナスデータ
                           #  datetime.datetime(2024, 10, 10, 9, 25, 0),  # いいマイナスデータ
                           #  datetime.datetime(2023, 9, 10, 23, 40, 6),  # 謎の飛びデータ
                           #  datetime.datetime(2023, 9, 23, 23, 40, 6),  # Break系のいいマイナスデータ
                           #  datetime.datetime(2023, 3, 6, 23, 40, 6),  # 注目！いいマイナスデータ
                           #  datetime.datetime(2022, 2, 6, 23, 40, 6),  # いいマイナスデータ
                           # datetime.datetime(2022, 2, 21, 23, 40, 6),  # いいマイナスデータ
                           datetime.datetime(2025, 6, 17, 14, 15, 6),
                           'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_m5_df.csv',
                           'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_s5_df.csv',
                           600,
                           1,
                           " テスト" + memo,
                           True,  # グラフの描画あり
                           ""
                           )
elif mode == 2:
    tk.line_send("検証期間 ここから連続↓")
    i = 1
    res = ""
    for item in loop:
        intest = ci.Inspection(pi.wrap_predict_turn_inspection_test,
                               False,
                               item,  # いいマイナスデータ
                               'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_m5_df.csv',
                               'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_s5_df.csv',
                               600,
                               1,
                               " テスト" + memo,
                               True,  # グラフの描画あり
                               ""
                               )
        res = res + '\n' + intest.res_all
        print(i, "つ目が終了")
    tk.line_send("検証期間 ここまで連続↑", '\n', res, '\n', '\n')
    print(res)

elif mode == 3:
    tk.line_send("検証期間　繰り返し×繰り返し")
    res = ""
    m = 0.5
    t = 3
    l = 2.2
    ch = 3
    rat = 0.36
    ltmch = str(m) + "/" + str(t) + "/"+ str(l) + "/" + str(ch)
    # 条件の登録
    # overFilter 1=Overなし 0=全部 -1=Overのみ
    # skipFilter 1=skipなしのみ　0=全部　-1=Skipありのみ
    pt = [
        # {"ret_count": 3, "min_resi_stg": 0, "max_resi_stg": 8, "over_filter": 1, "skip_filter": -1,
        #  "lc": l, "tp": t, "margin": m, "lc_change": ch, "rat": rat, "pat": 1, "c": "c3"},
        # {"ret_count": 3, "min_resi_stg": 0, "max_resi_stg": 8, "over_filter": 1, "skip_filter": -1,
        #  "lc": l, "tp": t, "margin": m, "lc_change": ch, "rat": rat, "pat": 2, "c": "c3"},
        #
        # {"ret_count": 3, "min_resi_stg": 0, "max_resi_stg": 8, "over_filter": 1, "skip_filter": -1,
        #  "lc": l, "tp": l, "margin": m, "lc_change": ch, "rat": rat, "pat": 1, "c": "c3"},
        # {"ret_count": 3, "min_resi_stg": 0, "max_resi_stg": 8, "over_filter": 1, "skip_filter": -1,
        #  "lc": l, "tp": l, "margin": m, "lc_change": ch, "rat": rat, "pat": 2, "c": "c3"},

        # {"ret_count": 3, "min_resi_stg": 0, "max_resi_stg": 8, "over_filter": 1, "skip_filter": -1,
        #  "lc": 2.2, "tp": 2.2, "margin": 0.6, "lc_change": 3, "rat":  0.36, "pat": 2, "c": "c3[強]"},
        #
        # {"ret_count": 3, "min_resi_stg": 0, "max_resi_stg": 8, "over_filter": 1, "skip_filter": -1,
        #  "lc": 2.2, "tp": 2.2, "margin": 0.6, "lc_change": 3, "rat":  0.7, "pat": 2, "c": "c3 ratのみ"},

        {"ret_count": 3, "min_resi_stg": 8, "max_resi_stg": 10, "over_filter": 9, "skip_filter": -1,
         "lc": 2.2, "tp": 2.2, "margin": 0.6, "lc_change": 3, "rat": 0.36, "pat": 2, "c": "c3 stgのみ"},

        {"ret_count": 3, "min_resi_stg": 8, "max_resi_stg": 10, "over_filter": 9, "skip_filter": -1,
         "lc": 2.2, "tp": 2.2, "margin": 0.6, "lc_change": 3, "rat": 0.36, "pat": 3, "c": "c3"},

    ]
    for d in pt:
        min_st = d['min_resi_stg']
        max_st = d['max_resi_stg']
        of = d["over_filter"]
        sf = d["skip_filter"]
        lc = d["lc"]
        tp = d["tp"]
        m = d["margin"]
        pat = d['pat']
        rat = d['rat']
        # 既存の "c" に追記
        d["c"] += f"_of:{of},sf:{sf},lc={lc},tp={tp},m={m},min_st={min_st},max_st={max_st},pat={pat},rat={rat}"
    # 確認
    for d in pt:
        print(d["c"])

    i = 1
    y = 1
    for each_pt in pt:
        res = res + '\n' + each_pt['c']
        for item in loop:
            intest = ci.Inspection(pi.wrap_predict_turn_inspection_looptest,
                                   False,
                                   item,  # いいマイナスデータ
                                   'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_m5_df.csv',
                                   'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_s5_df.csv',
                                   # 600,
                                   4900,
                                   3,
                                   " テスト" + memo,
                                   False,  # グラフの描画あり
                                   each_pt
                                   )
            res = res + '\n' + intest.res_all
            print(i, "つ目が終了")
        res = res + '\n' + '■■■■■(' + str(y) + "/" + str(len(pt)) + ")" + '\n'
        y = y + 1
    print(res)
    chunk_size = 1900
    for i in range(0, len(res), chunk_size):
        chunk = res[i:i + chunk_size]
        tk.line_send("検証期間" + chunk)
    tk.line_send("検証期間　ここまで連続↑")







