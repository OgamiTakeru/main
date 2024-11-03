import pandas as pd
import numpy as np
import json
import time
import threading  # 定時実行用
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.tree import plot_tree
import time, datetime, dateutil.parser, pytz  # 日付関係
import pickle
import fGeneric as f
import tokens as tk
from IPython.display import display, HTML

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
    ans_col = "plus_minus"  # 教師列の設定
    create_model_name = "DoublePeakBreak"  # モデル排出名の設定

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
        imp = imp + "," + X.columns.values[i] + ":" + str(round(RFC.feature_importances_[i], 3))
    print(imp)
    # 学習モデルの保存
    model_path = tk.folder_path + create_model_name + '.pickle'
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
    data_df.to_csv(tk.folder_path + 'testMLres.csv', index=False)  # 記録用

    return ans


def delete_cols(data_df):
    # データのNoneを埋める
    data_df.fillna(0, inplace=True)  # 0埋めしておく

    # ピーク関係にある項目たち
    data_df.drop(['order_time', 'end_time'], axis=1, inplace=True)  #
    data_df.drop(['take', 'end', 'take_position_price', 'settlement_price'], axis=1, inplace=True)  #
    data_df.drop(['name', 'res'], axis=1, inplace=True)  #
    data_df.drop(['pl', 'pl_per_units'], axis=1, inplace=True)  #
    data_df.drop(['position_keeping_time'], axis=1, inplace=True)  #
    data_df.drop(['tp_price', 'lc_price'], axis=1, inplace=True)  #
    data_df.drop(['units'], axis=1, inplace=True)  #
    data_df.drop(['max_plus', 'max_minus'], axis=1, inplace=True)  #
    data_df.drop(['double_top_strength', 'order_time_datetime'], axis=1, inplace=True)  #
    return data_df


def filterDF(df):
    """
    色々とフィルターする
    :param df:
    :return:
    """
    # df = df[df["take_position_flag"] == True]  # Trueだけ
    # df = df[df["river_count"] == 2]
    return df


def date_create(file_path):
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
df = date_create(tk.folder_path + '1103_120202_main_analysis_ans.csv')
pd.options.display.max_columns = None
print("DF")
# df.to_csv(tk.folder_path + 'testML.csv', index=False)  # 記録用
ml_ans = mlExe(df)