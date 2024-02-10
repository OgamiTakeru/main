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
from sklearn.tree import plot_tree
import graphviz



rescsv_path = 'C:/Users/taker/Desktop/inspectionml.csv'
df = pd.read_csv(rescsv_path, sep=",", encoding="utf-8")
print(df)

#学習用ラベルの削除と登録
target_col = "first_arrive_lo"
# X = df.drop(['future_gap'], axis=1)
# Y = df['future_gap']
X = df.drop([target_col], axis=1)
Y = df[target_col]
(train_x, test_x ,train_y, test_y) = train_test_split(X, Y, test_size = 0.3,random_state=123)

# 決定木での分析
DTC=DecisionTreeClassifier(max_depth=5, random_state=7)
DTC.fit(train_x,train_y)
#学習データ・テストデータそれぞれの正解率
train_score=DTC.score(train_x,train_y)
test_score=DTC.score(test_x,test_y)
print('Tree train Score:',train_score,'test score:',test_score)
plt.figure(figsize=(15, 10))
plot_tree(DTC, feature_names=train_x.columns, class_names=True, filled=True)
# plt.show()

#ランダムフォレストでの結果
RFC=RandomForestClassifier(random_state=777)
RFC.fit(train_x,train_y)
#学習データテストデータそれぞれの正解率(と寄与率)
train_score=RFC.score(train_x,train_y)
test_score=RFC.score(test_x,test_y)
print('RFC train score:',train_score,'test_score:',test_score)
#参考用
imp=""
for i in range(len(df.columns.values)-1):
    imp=imp + "," + df.columns.values[i]+ ":" + str(round(RFC.feature_importances_[i],3))
print(imp)
#
# model_path = 'C:/Users/taker/Desktop/testML.pickle'
# with open(model_path, mode='wb') as f:
#     pickle.dump(RFC, f, protocol=2)
#
#
# # 学習モデルの読み込み、適用
# # モデルのオープン
# with open(model_path, mode='rb') as f:
#     RFC = pickle.load(f)
# # 評価データ
# ml_datas = df.drop(['ans'], axis=1)
# # モデルを用いた予測
# ans_ml = RFC.predict(ml_datas)
# print(ans_ml)
# df['ans_ml'] = ans_ml  # 元データに結果を追記する（確認用）
# # data_df['time_jp'] = time_temp
# # data_df['go_trend'] = trend_temp
# df.to_csv('C:/Users/taker/Desktop/ml_ans.csv', index=False)  # 記録用