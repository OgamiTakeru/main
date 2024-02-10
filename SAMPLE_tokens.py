import requests  # Line送信用
import datetime  # 時刻の取得用

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
    temp = ""
    # 複数の引数を一つにする（数字が含まれる場合があるため、STRで文字化しておく）
    for item in msg:
        temp = temp + " " + str(item)
    requests.post(api_url, headers=TOKEN_dic, data={'message': temp})  # 送信を関数化
    print("     [Line]", temp)  # コマンドラインにも表示


# ログフォルダ設定
folder_path = ""


def f_write(path, msg):
    f = open(path, 'r', encoding='Shift-JIS')
    f_data = f.read()
    f_data = '{"date":' + str(datetime.datetime.now().replace(microsecond=0)) + "," + msg + f_data + '\n'  # 最後に改行する
    f = open(path, 'w', encoding='Shift-JIS')
    f.write(f_data)
    f.close()
