import pandas as pd
import numpy as np
import json
import time
import threading  # 定時実行用
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.tree import plot_tree
import matplotlib.pyplot as plt
import time, datetime, dateutil.parser, pytz  # 日付関係
import pickle
import fGeneric as f
import tokens as tk

from tqdm import tqdm
from sklearn.metrics import f1_score
from sklearn.model_selection import GridSearchCV
import graphviz


#機械学習の実施
def mlExe(data_df):
    """
    機械学習を実施する。将来を見据えて教師列の指定、モデルをエクスポートするときの名前も指定できるようにする
    :param data_df:
    :param ans_col: 　今は受け取らない（以下で変数で設定）
    :param create_model_name: 今は受け取らない（以下で変数で設定）
    :return:
    """
    print("ML開始")
    ans_col = "tp"  # 教師列の設定
    create_model_name = "DoublePeak"  # モデル排出名の設定

    # (1)機械学習の実施、モデルの作成
    X = data_df.drop([ans_col], axis=1)  # go_trend_flag
    Y = data_df[ans_col]
    print("X")
    print(X)
    print("Y")
    print(Y)

    (train_x, test_x, train_y, test_y) = train_test_split(X, Y, test_size=0.3, random_state=123)

    DTC = DecisionTreeClassifier(random_state=777)
    DTC.fit(train_x, train_y)

    # 学習データ・テストデータそれぞれの正解率
    train_score = DTC.score(train_x, train_y)
    test_score = DTC.score(test_x, test_y)
    print('Tree train Score:', train_score, 'test score:', test_score)

    # ランダムフォレストでの結果
    RFC = RandomForestClassifier(random_state=777,max_depth=50)
    RFC.fit(train_x, train_y)
    # 学習データテストデータそれぞれの正解率(と寄与率)
    train_score = RFC.score(train_x, train_y)
    test_score = RFC.score(test_x, test_y)
    print('RFC train score:', train_score, 'test_score:', test_score)

    # 結果の表示
    imp = ""
    for i in range(len(data_df.columns.values) - 1):
        imp = imp + "," + data_df.columns.values[i] + ":" + str(round(RFC.feature_importances_[i], 3))
    print(imp)
    # 学習モデルの保存
    model_path = 'C:/Users/taker/Desktop/oanda_logs/' + create_model_name + '.pickle'
    with open(model_path, mode='wb') as f:
        pickle.dump(RFC, f, protocol=2)

    # (2)学習モデルの読み込み、適用
    # モデルのオープン
    with open(model_path, mode='rb') as f:
        RFC = pickle.load(f)
    # 評価データ
    ml_datas = data_df.drop([ans_col], axis=1)
    # モデルを用いた予測
    ans = RFC.predict(ml_datas)
    print(ans)
    data_df['ans'] = ans  # 元データに結果を追記する（確認用）
    data_df.to_csv('C:/Users/taker/Desktop/testMLres.csv', index=False)  # 記録用

    return ans


def delete_cols(data_df):
    # データのNoneを埋める
    data_df.fillna(0, inplace=True)  # 0埋めしておく
    # 不要項目の削除
    # data_df.drop(['time', 'time_jp'], axis=1, inplace=True)  # 時間関係
    # data_df.drop(['open', 'close', 'high', 'low', 'inner_high', 'inner_low', 'bb_upper', 'bb_lower'],axis=1, inplace=True)  # 価格情報ありの項目
    # data_df.drop(['body_abs'], axis=1, inplace=True)
    # ピーク関係にある項目たち
    data_df.drop(['decision_time', 'decision_price'], axis=1, inplace=True)  #
    data_df.drop(['lc_range', 'tp_range'], axis=1, inplace=True)  #
    data_df.drop(['expect_direction'], axis=1, inplace=True)  #
    data_df.drop(['position', 'position_price', "position_time", "end_time_of_inspection"], axis=1, inplace=True)  #
    data_df.drop(['max_plus', 'max_plus_time', 'max_plus_past_time'], axis=1, inplace=True)  #
    data_df.drop(['max_minus', 'max_minus_time', 'max_minus_past_time'], axis=1, inplace=True)  #
    data_df.drop(['lc_time', 'lc_time_past', 'lc_res'], axis=1, inplace=True)  #
    data_df.drop(['tp_time', 'tp_time_past', 'tp_res'], axis=1, inplace=True)  #
    data_df.drop(['max_plus_all_time', 'max_plus_time_all_time', 'max_plus_past_time_all_time'], axis=1, inplace=True)  #
    data_df.drop(['max_minus_all_time', 'max_minus_time_all_time', 'max_minus_past_time_all_time'], axis=1, inplace=True)  #
    data_df.drop(['lc'], axis=1, inplace=True)  #
    # data_df.drop(['tp'], axis=1, inplace=True)  #
    return data_df


def filterDF(df):
    """
    色々とフィルターする
    :param df:
    :return:
    """
    df = df[df["take_position_flag"] == True]  # Trueだけ
    df = df[df["river_count"] == 2]
    return df


def fileFormatCreate(file_path):
    """
    ファイルを読み込み、適切なデータにし、データを返却する
    :return:
    """
    # ファイルの読み込み
    rescsv_path = file_path  # 'C:/Users/taker/Desktop/oanda_logs/ダブルトップmain_analysis_ans.csv'
    df = pd.read_csv(rescsv_path, sep=",", encoding="utf-8")

    # データの形式を成型する（時間や価格情報を削除する）
    df = delete_cols(df)
    df = filterDF(df)

    # FalseとTrueがNG？
    # df.replace([True, 1], [False, -1], inplace =True)
    df.replace(True, 1, inplace = True)
    df.replace(False, -1, inplace = True)
    print(df.head(5))

    return df


# メイン処理
df = fileFormatCreate(tk.folder_path + 'double_top_main_analysis_ans_latest.csv')
print("DF")
print(df)
ml_ans = mlExe(df)