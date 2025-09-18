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
accountIDl2 = ""
access_tokenl = ''    # ★★★
environmentl = "live"  # 本番は"live"

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

    # ■■■Discard
    # ■履歴の送信（これだけ独立）
    if "検証期間" in message:
        if "LONG" in message:
            # 【長期間の検証用】
            WEBHOOK_URL = ""
            data = {"content": "@everyone " + message,
                    "allowed_mentions": {
                        "parse": ["everyone"]
                    }
                    }
            requests.post(WEBHOOK_URL, json=data)
            return 0

        # 【短期間専用　よく動かすやつ】履歴送信の場合は、サードのみに送信　 # ■Discord３ テスト結果を送信する用
        WEBHOOK_URL = ""
        data = {"content": "@everyone " + message,
                "allowed_mentions": {
                    "parse": ["everyone"]
                }
                }
        requests.post(WEBHOOK_URL, json=data)
        return 0

    # ■■■  通常のDiscord送信　■■■　　最悪これ以下だけあればいい
    WEBHOOK_URL = ""
    data = {"content": "@everyone " + message,
            "allowed_mentions": {
                    "parse": ["everyone"]
                }
            }
    requests.post(WEBHOOK_URL, json=data)

    # ■Discord2 共有サーバーに送付(テストなので25/8には消去)
    # line_to_friend(message)  # オプション（オーダーと結果のみを送信する。人に送りたくなければなくて負い）

    # ■コマンドラインに表示
    print("     [Disc]", message)  # コマンドラインにも表示


def line_to_friend(meg):
    """
    メッセージを受け取り、内容によって共有のDiscordに通知を送信する
    """
    print("サブ", meg)
    if "■■■解消:" in meg or "★オーダー発行" in meg or "test from Webfook" in meg:
        # 指定の文字を含む場合のみ、送信
        WEBHOOK_URL = ""
        data = {"content":meg}
        requests.post(WEBHOOK_URL, json=data)
    else:
        pass


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
path_log = ""  # ★★★

# 結果核のようようCSVファイル
path_csv = ""

# ログフォルダ設定
folder_path = ""

# 読み込み設定ファイル（条件を途中で変えられるように）
setting_folder_path = ""

# 検討フォルダ用
inspection_data_cache_folder_path = ''

