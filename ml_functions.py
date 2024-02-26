####まだこれは使っていない（いずれ使う、というか切り替える。）
####mainからのimport時におかしなことになるため

import pandas as pd
import numpy as np
import json
import time
import threading  # 定時実行用
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import train_test_split, GridSearchCV
import matplotlib.pyplot as plt
import time, datetime, dateutil.parser, pytz  # 日付関係
import pickle
from tqdm import tqdm
from sklearn.metrics import f1_score
from sklearn.model_selection import GridSearchCV

# 極値探索用
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.signal import argrelmin,argrelmax

# 自作ファイルインポート
import oanda_program.oanda_class as oanda_class

def ml_grid(data_df, ans_col):
    X = data_df.drop([ans_col], axis=1)  # go_trend_flag
    Y = data_df[ans_col]
    (train_X, test_X, train_y, test_y) = train_test_split(X, Y, test_size=0.3, random_state=123)
    # 条件設定
    max_score = 0
    SearchMethod = 0
    RFC_grid = {RandomForestClassifier(): {"n_estimators": [100,200],
                                           # "criterion": ["gini"],
                                           "max_depth": [5,10,50,70,100,None],
                                           # "random_state": [i for i in range(0, 101)]
                                           }}
    # RFC_grid = {RandomForestClassifier(): {"n_estimators": [i for i in range(1, 21)],
    #                                        "criterion": ["gini", "entropy"],
    #                                        "max_depth": [i for i in range(1, 5)],
    #                                        "random_state": [i for i in range(0, 101)]
    #                                        }}

    # ランダムフォレストの実行
    for model, param in tqdm(RFC_grid.items()):
        clf = GridSearchCV(model, param)
        clf.fit(train_X, train_y)
        pred_y = clf.predict(test_X)
        score = f1_score(test_y, pred_y, average="micro")

        if max_score < score:
            max_score = score
            best_param = clf.best_params_
            best_model = model.__class__.__name__

    print("ベストスコア:{}".format(max_score))
    print("モデル:{}".format(best_model))
    print("パラメーター:{}".format(best_param))

    # ハイパーパラメータを調整しない場合との比較
    model = RandomForestClassifier()
    model.fit(train_X, train_y)
    score = model.score(test_X, test_y)
    print("")
    print("デフォルトスコア:", score)

#機械学習の実施
def ml_exe(data_df, ans_col, create_model_name):
    print("ML開始")
    # 学習モデルの読み込み、適用
    ##　以下機械学習 (目的関数の列名は引数で受け取る）
    X = data_df.drop([ans_col], axis=1)  # go_trend_flag
    Y = data_df[ans_col]
    (train_x, test_x, train_y, test_y) = train_test_split(X, Y, test_size=0.3, random_state=123)

    DTC = DecisionTreeClassifier(random_state=777)
    DTC.fit(train_x, train_y)

    ##学習データ・テストデータそれぞれの正解率
    train_score = DTC.score(train_x, train_y)
    test_score = DTC.score(test_x, test_y)
    print('Tree train Score:', train_score, 'test score:', test_score)

    ##ランダムフォレストでの結果
    RFC = RandomForestClassifier(random_state=777,max_depth=50)
    RFC.fit(train_x, train_y)
    ##学習データテストデータそれぞれの正解率(と寄与率)
    train_score = RFC.score(train_x, train_y)
    test_score = RFC.score(test_x, test_y)
    print('RFC train score:', train_score, 'test_score:', test_score)

    imp = ""
    for i in range(len(data_df.columns.values) - 1):
        imp = imp + "," + data_df.columns.values[i] + ":" + str(round(RFC.feature_importances_[i], 3))
    print(imp)

    # 学習モデルの保存
    model_path = 'C:/Users/taker/Desktop/oanda_datas/' + create_model_name + '.pickle'
    with open(model_path, mode='wb') as f:
        pickle.dump(RFC, f, protocol=2)

    # 学習モデルの読み込み、適用
    # モデルのオープン
    with open(model_path, mode='rb') as f:
        RFC = pickle.load(f)
    # 評価データ
    ml_datas = data_df.drop([ans_col], axis=1)
    # モデルを用いた予測
    ans = RFC.predict(ml_datas)
    print(ans)
    data_df['ans'] = ans  # 元データに結果を追記する（確認用）
    # data_df['time_jp'] = time_temp
    # data_df['go_trend'] = trend_temp
    # data_df.to_csv('C:/Users/taker/Desktop/testMLres.csv', index=False)  # 記録用

    return ans


# 目的変数：シンプルに現在の価格より上がっているかどうか
def add_ans_simple(data_df):
    data_df['temp_sa'] =  data_df['close'].shift(-1) - data_df['close'] #変化後ー変化前
    data_df['ans_up_down'] = data_df.apply(lambda x: add_ans_simple_sub(x), axis=1)
    data_df.drop(['temp_sa'], axis=1, inplace=True)  # 時間関係
    data_df.fillna(0, inplace=True)  # 0埋めしておく

    return data_df

def add_ans_simple_sub(x):  # InstrumentsCandles_exeから呼び出し
    if x.temp_sa > 0.016:  #+域で、規定幅よりも増えていた場合
        return 1
    elif x.temp_sa < -0.016:
        return -1
    else:
        return 0

# 目的変数：ボリバン関係の目的変数を集計する
def add_ans_bb(data_df):
    # (1)BBを超えている場合がある時、トレンドに行ったのか、単発だったのかの判断を実施する(UpperとLower同時の場合はupper優先）
    data_df['ans_over_counter'] = 0
    data_df['ans_over_counter_pm'] = 0
    for index, item in data_df.iterrows():# 行が進む（行index++)で、時が新しい！（通常とは逆）
        over_count = 0
        over_count_pm = 0
        search_range = 5
        up_border = 1  # 〇%以下の行を抽出する
        low_border = 99  # 〇%以上の行を抽出する
        if item['bb_over_ratio'] < up_border:
            # 上に突破している場合（この方式だと、上超え、下超えが二連続できた場合はエラーになるが）
            for i in range(search_range):
                if index + i < len(data_df)-1:  # data_dfの最終行は　len(deta\df)-1。column名があるため。
                    if data_df['bb_over_ratio'].iloc[index + i] < up_border:
                        over_count += 1
                        over_count_pm += 1
                    else:
                        break
        elif item['bb_under_ratio'] > low_border:
            # 下に突破している場合
            for i in range(search_range):
                if index + i < len(data_df)-1:  # data_dfの最終行は　len(deta\df)-1。column名があるため。
                    if data_df['bb_under_ratio'].iloc[index + i] > low_border:
                        over_count += 1
                        over_count_pm -= 1
                    else:
                        break
        else:
            trend_flag = 0  #何もない時にのみトレンドフラグを下げる
        # 結果出力
        data_df['ans_over_counter'].iloc[index] = over_count  # 何回bb越えが続いたか
        data_df['ans_over_counter_pm'].iloc[index] = over_count_pm  # 何回bb越えが続いたか

    # (2)上のOverCountがある前提で、Treandに入った行いフラグを立てる（
    data_df['ans_go_trend'] = 0
    skip_counter = 0
    for index, item in data_df.iterrows():# 行が進む（行index++)で、時が新しい！（通常とは逆）
        if skip_counter > 0:
            # 確認済（SKIPCOUNTの範囲内）であれば飛ばす
            skip_counter -= 1
        else:
            if item['ans_over_counter'] > 1:
                # 突破カウンターが１より大きい場合（１の場合は「逆張り対応範囲」）
                i = 1
                while index + i < len(data_df)-1 and data_df['ans_over_counter'].iloc[index + i] != 0:
                    skip_counter += 1
                    i += 1
                if skip_counter > 0:
                    data_df['ans_go_trend'].iloc[index] = 1
    # (2)上のOverCountがある前提で、Treandに入った行いフラグを立てる（
    data_df['ans_go_trend_pm'] = 0
    skip_counter = 0
    for index, item in data_df.iterrows():# 行が進む（行index++)で、時が新しい！（通常とは逆）
        if skip_counter > 0:
            # 確認済（SKIPCOUNTの範囲内）であれば飛ばす
            skip_counter -= 1
        else:
            if item['ans_over_counter_pm'] > 1:
                # 突破カウンターが１より大きい場合（１の場合は「逆張り対応範囲」）
                i = 1
                while index + i < len(data_df)-1 and data_df['ans_over_counter_pm'].iloc[index + i] > 0:
                    skip_counter += 1
                    i += 1
                if skip_counter > 0:
                    data_df['ans_go_trend_pm'].iloc[index] = 1
            elif item['ans_over_counter_pm'] < -1:
                # 突破カウンターが１より大きい場合（１の場合は「逆張り対応範囲」）
                i = 1
                while index + i < len(data_df)-1 and data_df['ans_over_counter_pm'].iloc[index + i] < 0:
                    skip_counter += 1
                    i += 1
                if skip_counter > 0:
                    data_df['ans_go_trend_pm'].iloc[index] = -1

    # (3)go_trendの逆。折り返しとみられる「BB超え」に対してフラグを付ける
    data_df['ans_r_go_trend'] = 0
    for index, item in data_df.iterrows():# 行が進む（行index++)で、時が新しい！（通常とは逆）
        if item['ans_over_counter'] == 1:
            data_df['ans_r_go_trend'].iloc[index] = 1

    # (3)go_trendの逆。折り返しとみられる「BB超え」に対してフラグを付ける
    data_df['ans_r_go_trend_pm'] = 0
    for index, item in data_df.iterrows():# 行が進む（行index++)で、時が新しい！（通常とは逆）
        if item['ans_over_counter_pm'] == 1:
            data_df['ans_r_go_trend_pm'].iloc[index] = 1
        elif item['ans_over_counter_pm'] == -1:
            data_df['ans_r_go_trend_pm'].iloc[index] = -1  # 下に凸

    # 強トレンド（プラスマイナス）を抽出
    data_df['ans_strong_trend_pm'] = 0
    for index, item in data_df.iterrows():# 行が進む（行index++)で、時が新しい！（通常とは逆）
        if item['ans_over_counter_pm'] >= 4:
            data_df['ans_strong_trend_pm'].iloc[index] = 1
            # item['ans_strong_trend_pm'] = 1
        elif item['ans_over_counter_pm'] <= -4:
            data_df['ans_strong_trend_pm'].iloc[index] = -1

    # 消す候補の列をここで書いておく
    # data_df.drop(['ans_over_counter'], axis=1, inplace=True)
    # data_df.drop(['ans_over_counter_pm'], axis=1, inplace=True)
    # data_df.drop(['ans_go_trend'], axis=1, inplace=True)
    # data_df.drop(['ans_go_trend_pm'], axis=1, inplace=True)
    # data_df.drop(['ans_r_go_trend'], axis=1, inplace=True)
    # data_df.drop(['ans_r_go_trend_pm'], axis=1, inplace=True)
    # data_df.drop(['ans_strong_trend_pm'], axis=1, inplace=True)


    paths = 'C:/Users/taker/Desktop/test_MLbase.csv'
    data_df.to_csv(paths, index=False)  # 記録用
    return data_df


# 極値探索
def ex_ans(data_df):
    base = 7  # 奇数で統一
    data_df['ans_ex'] = 0
    for index, data in data_df.iterrows():
        # 低極値かの判断
        if data['low'] == data_df[index - 3:index + 4]['low'].min():
            data_df['ans_ex'].iloc[index] = -1
        # 高極値かの判断
        if data['high'] == data_df[index - 3:index + 4]['high'].max():
            data_df['ans_ex'].iloc[index] = 1
    return data_df


# 〇pipsの変動が、△個以内にある場合
def pips_ans(data_df):
    base = 6  # 奇数で統一
    data_df['ans_pips'] = 0
    for index, data in data_df.iterrows():
        # 低極値かの判断
        high = abs(round(data["close"] - data_df[index:index + base]['inner_high'].max(),3))
        low = abs(round(data["close"] - data_df[index:index + base]['inner_low'].min(),3))
        if high > 0.1 or low > 0.1:
            data_df['ans_pips'].iloc[index] = 1
        elif high > 0.05 or low > 0.05:
            data_df['ans_pips'].iloc[index] = 1
    return data_df


# 目的変数：ロスカになったかどうかの判断
def add_ans_lctp(data_df):
    data_df['ans_tp_lc'] = 0
    # data_df['tp_lc_check'] = 0
    # data_df['tp_line_check'] = 0
    # data_df['lc_line_check'] = 0
    for index, item in data_df.iterrows():  # 行が進む（行index++)で、時が新しい！（通常とは逆）
        test_counter = 0
        # 下方向に逆張りの場合
        if item['bb_over_ratio'] < 1:
            lc_line = round(item['close'] + abs(item['body_3mean']), 3)  # 正確にはCloseではないが、、、(bit,askで異なるため）
            tp_line = round(item['close'] - abs(item['body_3mean']), 3)
            # data_df['tp_line_check'].iloc[index] = tp_line
            # data_df['lc_line_check'].iloc[index] = lc_line
            for i in range(2):
                # 下への動きが＋の為、high方向の場合はロスカっと
                # test_counter += 1
                if data_df['high'].iloc[index + i] > lc_line:
                    data_df['ans_tp_lc'].iloc[index] = -1  # LC時
                    # data_df['tp_lc_check'].iloc[index] = test_counter
                    break
                elif data_df['low'].iloc[index + i] < tp_line:
                    data_df['ans_tp_lc'].iloc[index] = 1  # TP時
                    # data_df['tp_lc_check'].iloc[index] = test_counter
                    break
        # 上方向に逆張りの場合
        elif item['bb_under_ratio'] > 99:
            lc_line = round(item['close'] - abs(item['body_3mean']) * 1.15, 3)  # 正確にはCloseではないが、、、(bit,askで異なるため）
            tp_line = round(item['close'] + abs(item['body_3mean']) * 1.3, 3)
            # data_df['tp_line_check'].iloc[index] = tp_line
            # data_df['lc_line_check'].iloc[index] = lc_line
            i = 1
            for i in range(2):
                # 上への動きが＋の為、low方向の場合はロスカっと
                test_counter += 1
                if data_df['high'].iloc[index + i] > tp_line:
                    data_df['ans_tp_lc'].iloc[index] = 1  # TP時
                    # data_df['tp_lc_check'].iloc[index] = test_counter
                    break
                elif data_df['low'].iloc[index + i] < lc_line:
                    data_df['ans_tp_lc'].iloc[index] = -1  # LC時
                    # data_df['tp_lc_check'].iloc[index] = test_counter
                    break
                # 次の行へ
                i += 1
        else:
            continue
    return(data_df)


def del_base_col(data_df):
    # データのNoneを埋める
    data_df.fillna(0, inplace=True)  # 0埋めしておく
    # 不要項目の削除
    data_df.drop(['time', 'time_jp'], axis=1, inplace=True)  # 時間関係
    data_df.drop(['open', 'close', 'high', 'low', 'inner_high', 'inner_low', 'bb_upper', 'bb_lower'],axis=1, inplace=True)  # 価格情報ありの項目
    data_df.drop(['body_abs'], axis=1, inplace=True)
    return data_df


