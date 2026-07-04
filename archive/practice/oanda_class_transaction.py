###トランザクションデータの取得について（これだけクラスと分割している（理由忘れた））

import pandas as pd
import numpy as np
import json
import time
import matplotlib.pyplot as plt
import time, datetime, dateutil.parser, pytz  # 日付関係
import pickle
import requests

# 自作ファイルインポート
import programs.classOanda as oanda_class
import programs.tokens as tk
import oandapyV20.endpoints.instruments as instruments
from oandapyV20 import API
from oandapyV20.endpoints.trades import TradeCRCDO

import oandapyV20.endpoints.transactions as trans

# 初期設定＋oandaクラスインスタンス生成
accountID = tk.accountID
access_token = tk.access_token
environment = "practice"  # デモ口座 本番は"live"
oa = oanda_class.Oanda(accountID, access_token,environment)  # クラスインスタンス生成
api = API(access_token=access_token, environment=environment)
price_dic = oa.NowPrice_exe("USD_JPY")
range_params = {  # 初期値。とりあえず数字はテキトーだが書き換わるので問題なし。最大１０００くらいだった気がする
    "to": 42154,  # 若い番号（古い）
    "from": 42026  # 大きい番号（直近）　toとfromの間は１０００以下であること！（API仕様）
}


def get_base_data():
    """
    トランザクションデータを取得する関数。取得範囲は、辞書形式でIDを指定し、最大１０００程度（わすれた）
    とはいえ、最新の取引IDは？といわれてもわからないため、直近のトランザクションを取得、というわけではない。
    この最大数以上取りたい場合や、直近のデータが欲しい場合は、get_base_data_multiを利用する。
    :return:
    """
    oa = oanda_class

    # APIでトランザクションを取得
    ep = trans.TransactionIDRange(accountID=accountID, params=range_params)  # paramsでto/fromを辞書で指定。
    resp = api.request(ep)
    print(json.dumps(resp, indent=2))

    # transactionの内の配列データを取得する
    transactions = resp['transactions']
    print(len(transactions))

    all_info = []
    for item in transactions:
        print("id=", item["id"])
        # 考えるのめんどいので、必要項目だけ辞書形式にしてしまう
        dict = {
            "id": item["id"],
            "time": item["time"],
            "type": item["type"],
            "reason": item["reason"],
        }
        if "units" in item:
            dict["units"] = item["units"]
        else:
            print("  OrderCancel")
            dict["units"] = 0
            pass
        # priceを含む場合（オーダーのキャンセル以外はpriceが入る）
        if "price" in item:
            dict['price'] = item['price']
        else:
            print("  OrderCancel")
            dict['price'] = 0
            pass
        # ポジション解消時にある項目
        if "pl" in item:
            dict["pl"] = item["pl"]
        else:
            dict["pl"] = 0
        # ポジションオーダー時にある項目
        if "takeProfitOnFill" in item:
            dict["price_tp"] = item["takeProfitOnFill"]["price"]
        else:
            dict["price_tp"] = 0
        if "stopLossOnFill" in item:
            dict["price_lc"] = item["stopLossOnFill"]["price"]
        else:
            dict["price_lc"] = 0

        # 配列に追加する
        all_info.append(dict)

    t_df = pd.DataFrame(all_info)
    t_df['time_jp'] = t_df.apply(lambda x: oa.iso_to_jstdt(x, 'time'), axis=1)  # 日本時刻を追加する
    print(t_df)
    t_df.to_csv(tk.folder_path + 'transaction.csv', index=False, encoding="utf-8")
    print("トランザクションデータ取得完了")

    return t_df

def get_base_data_multi(roop,num):
    """
    最新のデータから、N個さかのぼった分のデータをトランザクションデータを取得する。
    処理としては、まず最新の取引IDを取得し、そこからnum個分のデータを、roop回数取得する。
    numの最大値は、500(OandaのAPIの仕様上限。get_base_dataを利用してAPIを叩く事になる）
    例えば、num=3でroop=5とした場合、直近から３回分の取引データを５回分、ようするに直近１５回分の取引データを取得する。
    :param roop: N
    :param num:
    :return:
    """
    # 返却用DF
    for_ans = None
    # 最も新しいIDを取得する（TOに入れる用）
    oa = oanda_class
    ep = trans.TransactionIDRange(accountID=accountID, params={"to": 40746,"from": 40746})
    resp = api.request(ep)
    latestT = resp['lastTransactionID']

    for i in range(roop):
        params_temp = {
            "to": int(latestT),
            "from": int(latestT) - num + 1
        }
        ep = trans.TransactionIDRange(accountID=accountID, params=params_temp)
        resp = api.request(ep)
        # params内、toの変更
        latestT = int(latestT) - num

        # transactionの内の配列データを取得する
        transactions = resp['transactions']
        print(len(transactions))

        all_info = []
        for item in transactions:
            print("id=", item["id"])
            # print(item)
            # 考えるのめんどいので、必要項目だけ辞書形式にしてしまう
            dict = {
                "id": item["id"],
                "time": item["time"],
                "type": item["type"],
                # "reason": item["reason"],
            }
            # たまにreasonがないのが存在する。。41494とか
            if "reason" in item:
                dict["reason"] = item["reason"]
            else:
                dict["reason"] = 0
            #
            if "units" in item:
                dict["units"] = item["units"]
            else:
                dict["units"] = 0
            # ポジションオーダー時にある項目
            if "takeProfitOnFill" in item:
                if "price" in item["takeProfitOnFill"]:
                    dict["price_tp"] = item["takeProfitOnFill"]["price"]
                else:
                    dict["price_tp"] = "N"
            else:
                dict["price_tp"] = 0

            if "stopLossOnFill" in item:
                if "price" in item["stopLossOnFill"]:
                    dict["price_lc"] = item["stopLossOnFill"]["price"]
                else:
                    dict["price_lc"] = "N"
            else:
                dict["price_lc"] = 0
            # priceを含む場合（オーダーのキャンセル以外はpriceが入る）
            if "price" in item:
                dict['price'] = item['price']
            else:
                dict['price'] = 0
            # ポジション解消時にある項目
            if "pl" in item:
                dict["pl"] = item["pl"]
            else:
                dict["pl"] = 0

            # 配列に追加する
            all_info.append(dict)

        t_df = pd.DataFrame(all_info)
        t_df['time_jp'] = t_df.apply(lambda x: oa.iso_to_jstdt(x, 'time'), axis=1)  # 日本時刻を追加する

        for_ans = pd.concat([t_df, for_ans])  # 結果用dataframeに蓄積（時間はテレコ状態）

    # for_ans.to_csv(tk.folder_path + 'transaction_multi.csv', index=False, encoding="utf-8")
    print("トランザクションデータ取得完了")
    return for_ans

dt = get_base_data_multi(2,1000)

dt.to_csv(tk.folder_path + 'transaction_ans.csv', index=False, encoding="utf-8")