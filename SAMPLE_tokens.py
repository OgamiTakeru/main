import requests  # Line送信用
import datetime  # 時刻の取得用
import pandas as pd
import requests

# 練習環境
accountID = ""  # デモ    # ★★★
access_token = ''    # ★★★
environment = "practice"  # デモ口座 本番は"live"

# 本番環境
accountIDl = ""  # 本番用    # ★★★
access_tokenl = ''    # ★★★
environmentl = "live"  # デモ口座 本番は"live"

# Line環境設定
TOKEN = ''    # ★★★
api_url = 'https://notify-api.line.me/api/notify'
TOKEN_dic = {'Authorization': 'Bearer' + ' ' + TOKEN}
send_dic = {'message': 'Order'}


def line_send(*msg):
    # 関数は可変複数のコンマ区切りの引数を受け付ける
    message = ""
    # 複数の引数を一つにする（数字が含まれる場合があるため、STRで文字化しておく）
    for item in msg:
        message = message + " " + str(item)
    # 時刻の表示を作成する
    now_str = f'{datetime.datetime.now():%Y/%m/%d %H:%M:%S}'
    day = now_str[5:10]  # 01/01
    # day = day.replace("0", "")  # 1/1
    time = now_str[11:19]  # 09:10
    day_time = " (" + day + "_" + time + ")"
    # メッセージの最後尾に付ける
    message = message + day_time

    # ■LINE版　送信
    # requests.post(api_url, headers=TOKEN_dic, data={'message': message})  # 送信を関数化
    # print("     [Line]", message)  # コマンドラインにも表示

    # ■Discard　送信
    WEBHOOK_URL = ("")
    data = {"content": "@everyone " + message,
            "allowed_mentions": {
                    "parse": ["everyone"]
                }
            }
    requests.post(WEBHOOK_URL, json=data)

    # ■Discord2 共有サーバーに送付
    line_to_friend(message)

    # ■コマンドラインに表示
    print("     [Disc]", message)  # コマンドラインにも表示


def line_to_friend(meg):
    """
    メッセージを受け取り、内容によって共有のDiscordに通知を送信する
    """
    if "■■■解消:" in meg or "★オーダー発行" in meg:
        # 指定の文字を含む場合のみ、送信
        WEBHOOK_URL = ("")
        data = {")content": "@everyone " + meg,
                "allowed_mentions": {
                    "parse": ["everyone"]
                }
                }
        requests.post(WEBHOOK_URL, json=data)
    else:
        print(" LineToFriendは実施しない")




def f_write(path, msg):
    f = open(path, 'r', encoding='Shift-JIS')
    f_data = f.read()
    f_data = '{"date":' + str(datetime.datetime.now().replace(microsecond=0)) + "," + msg + f_data + '\n'  # 最後に改行する
    f = open(path, 'w', encoding='Shift-JIS')
    f.write(f_data)
    f.close()


def write_result(dic):
    new_data = pd.DataFrame([dic])

    try:
        # CSVに追記（ヘッダーの重複を避けるため `mode="a"` で書き込み）
        new_data.to_csv(folder_path + 'main_result.csv', mode='a', index=False, encoding="utf-8")
    except:
        print("結果書き込みエラーあり")




# ログ用ファイル設定
path_log = "C:/Users/taker/Dropbox/fx/log.txt"  # ★★★

# 結果核のようようCSVファイル
path_csv = ""

# ログフォルダ設定
folder_path = "C:/Users/taker/OneDrive/Desktop/oanda_logs/"

# 読み込み設定ファイル（条件を途中で変えられるように）
setting_folder_path = "C:/Users/taker/OneDrive/Desktop/OandaPrograms/main/"

# 検討フォルダ用
inspection_data_cache_folder_path = 'C:/Users/taker/Desktop/oanda_details/'

