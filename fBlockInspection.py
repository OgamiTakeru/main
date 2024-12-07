import fGeneric as f


def check_large_body_in_peak(block_ans):
    """
    対象となる範囲のデータフレームをループし（ブロックを探すのと並行してやるので、二回ループ作業してることになるが）
    突発を含むかを判定する
    ついでに、HighLowのプライスも取得する
    """
    # 大きい順に並べる
    s6 = "      "

    # 足や通過に依存する数字
    dependence_very_large_body_criteria = 0.2
    dependence_large_body_criteria = 0.1

    # 情報を取得する
    sorted_df_by_body_size = block_ans['data'].sort_values(by='body_abs', ascending=False)
    max_body_in_block = sorted_df_by_body_size["body_abs"].max()

    # ■極大の変動を含むブロックかの確認
    include_very_large = False
    for index, row in sorted_df_by_body_size.iterrows():
        if row['body'] >= dependence_very_large_body_criteria:
            include_very_large = True
            break
        else:
            include_very_large = False

    # ■突発的な変動を含むか判断する（大き目サイズがたくさんあるのか、数個だけあるのか＝突発）
    counter = 0
    for index, row in sorted_df_by_body_size.iterrows():
        # 自分自身が、絶対的に見て0.13以上と大きく、他の物より約2倍ある物を探す。（自分だけが大きければ、突然の伸び＝戻る可能性大）
        # 自分自身を、未達カウントするため注意が必要
        smaller_body = row['body_abs'] if row['body_abs'] != 0 else 0.00000001
        if max_body_in_block > dependence_large_body_criteria:
            if max_body_in_block / smaller_body > 1.8: #  > 0.561:
                # print(s6, "Baseが大きめといえる", smaller_body / max_body_in_block , "size", smaller_body, max_body_in_block, row['time_jp'])
                counter = counter + 1
            else:
                pass
                # print(s6, "自身より大き目（比率）", smaller_body / max_body_in_block, row['time_jp'])
        else:
            pass
            # print(s6, "baseBodyがそもそも小さい")
    if counter / (len(sorted_df_by_body_size)) >= 0.65:
        # 突発の伸びがあったと推定（急伸は戻る可能性大）　平均的に全部大きい場合は除く（大きくないものが75％以下の場合）
        # print(s6, "急伸の足を含む", counter / (len(sorted_df_by_body_size)), block_ans['data'].iloc[0]['time_jp'])
        include_large = True
    else:
        # print(s6, "急伸とみなさない")
        include_large = False

    return {
        "include_large": include_large,
        "include_very_large": include_very_large,
        "highest": sorted_df_by_body_size['high'].max(),
        "lowest": sorted_df_by_body_size['low'].min()
    }


def make_peak(data_df_origin):
    """
    渡された範囲で、何連続で同方向に進んでいるかを検証する
    :param data_df_origin: 直近が上側（日付降順/リバース）のデータを利用
    :return: Dict形式のデータを返伽
    """
    # コピーウォーニングのための入れ替え
    data_df = data_df_origin.copy()
    # 返却値を設定
    ans_dic = {
        "direction": 1,
        "count": 0,  # 最新時刻からスタートして同じ方向が何回続いているか
        "data_size": len(data_df),  # (注)元のデータサイズ
        "latest_image_price": 0,
        "oldest_image_price": 0,
        "oldest_time_jp": 0,
        "latest_time_jp": 0,
        "latest_price": 0,
        "oldest_price": 0,
        "latest_peak_price": 0,
        "oldest_peak_price": 0,
        "gap": 0.0001,
        "gap_high_low": 0.00001,
        "gap_close": 0.00001,
        "body_ave": 0.000001,
        "move_abs": 0.00001,
        "memo_time": 0,
        "data": data_df,  # 対象となるデータフレーム（元のデータフレームではない）
        "data_remain": data_df,  # 対象以外の残りのデータフレーム
        "support_info": {},
        "include_large": False,
        "include_very_large": False
    }
    if len(data_df) <= 1:  # データが１つ以上存在していれば実施
        return ans_dic

    # 実処理処理の開始
    base_direction = 0
    counter = 0
    for i in range(len(data_df)-1):
        tilt = data_df.iloc[i]['middle_price'] - data_df.iloc[i+1]['middle_price']
        if tilt == 0:
            tilt = 0.001
        tilt_direction = round(tilt / abs(tilt), 0)  # 方向のみ（念のためラウンドしておく）
        # ■初回の場合の設定。１行目と２行目の変化率に関する情報を取得、セットする
        if counter == 0:
            base_direction = tilt_direction
        else:
            # print(" 初回ではありません")
            pass

        # ■カウントを進めていく
        if tilt_direction == base_direction:  # 今回の検証変化率が、初回と動きの方向が同じ場合
            counter += 1
        else:
            break  # 連続が途切れた場合、ループを抜ける
    # ■対象のDFを取得し、情報を格納していく
    ans_df = data_df[0:counter+1]  # 同方向が続いてる範囲のデータを取得する
    ans_other_df = data_df[counter:]  # 残りのデータ

    if base_direction == 1:
        # 上り方向の場合、直近の最大価格をlatest_image価格として取得(latest価格とは異なる可能性あり）
        latest_image_price = ans_df.iloc[0]["inner_high"]
        oldest_image_price = ans_df.iloc[-1]["inner_low"]
        latest_peak_price = ans_df.iloc[0]["high"]
        oldest_peak_price = ans_df.iloc[-1]["low"]
    else:
        # 下り方向の場合
        latest_image_price = ans_df.iloc[0]["inner_low"]
        oldest_image_price = ans_df.iloc[-1]["inner_high"]
        latest_peak_price = ans_df.iloc[0]["low"]
        oldest_peak_price = ans_df.iloc[-1]["high"]
    #
    # ■平均移動距離等を考える
    body_ave = round(data_df["body_abs"].mean(),3)
    move_ave = round(data_df["moves"].mean(),3)

    # ■GAPを計算する（０の時は割る時とかに困るので、最低0.001にしておく）
    # gap = round(abs(latest_image_price - oldest_image_price), 3)  # MAXのサイズ感
    gap_close = round(abs(latest_image_price - ans_df.iloc[-1]["close"]), 3)  # 直近の価格（クローズの価格&向き不問）
    if gap_close == 0:
        gap_close = 0.001
    else:
        gap_close = gap_close

    gap = round(abs(latest_image_price - oldest_image_price), 3)  # 直近の価格（クローズの価格&向き不問）
    if gap == 0:
        gap = 0.001
    else:
        gap = gap

    gap_high_low = round(abs(latest_peak_price - oldest_peak_price), 3)  # 直近の価格（クローズの価格&向き不問）
    if gap_high_low == 0:
        gap_high_low = 0.001
    else:
        gap_high_low = gap_high_low

    # ■　一旦格納する
    # 表示等で利用する用（機能としては使わない
    memo_time = f.str_to_time_hms(ans_df.iloc[-1]["time_jp"]) + "_" + f.str_to_time_hms(
        ans_df.iloc[0]["time_jp"])
    # 返却用(Simple データを持たない表示用)
    ans_dic = {
        "direction": base_direction,
        "count": counter+1,  # 最新時刻からスタートして同じ方向が何回続いているか
        "data_size": len(data_df),  # (注)元のデータサイズ
        "latest_image_price": latest_image_price,
        "oldest_image_price": oldest_image_price,
        "oldest_time_jp": ans_df.iloc[-1]["time_jp"],
        "latest_time_jp": ans_df.iloc[0]["time_jp"],
        "latest_price": ans_df.iloc[0]["close"],
        "oldest_price": ans_df.iloc[-1]["open"],
        "latest_peak_price": latest_peak_price,
        "oldest_peak_price": oldest_peak_price,
        "gap": gap,
        "gap_high_low": gap_high_low,
        "gap_close": gap_close,
        "body_ave": body_ave,
        "move_abs": move_ave,
        "memo_time": memo_time,
        "data": ans_df,  # 対象となるデータフレーム（元のデータフレームではない）
        "data_remain": ans_other_df,  # 対象以外の残りのデータフレーム
    }

    ans_dic['include_large'] = check_large_body_in_peak(ans_dic)['include_large']
    ans_dic['include_very_large'] = check_large_body_in_peak(ans_dic)['include_very_large']
    ans_dic['highest'] = check_large_body_in_peak(ans_dic)['highest']
    ans_dic['lowest'] = check_large_body_in_peak(ans_dic)['lowest']

    # 返却する
    return ans_dic


def make_peak_with_skip(data_df_origin) -> dict[str, any]:
    """
    渡された範囲で、何連続で同方向に進んでいるかを検証する
    ただし方向が異なる１つ（N個）を除去しても方向が変わらない場合、延長する
    :param data_df_origin: 直近が上側（日付降順/リバース）のデータを利用
    :return: Dict形式のデータを返却　（冒頭で定義）
    """
    # コピーウォーニングのための入れ替え
    data_df = data_df_origin.copy()
    # 返却値の設定
    ans_dic = {
        "direction": 1,
        "count": 0,  # 最新時刻からスタートして同じ方向が何回続いているか
        "data_size": len(data_df),  # (注)元のデータサイズ
        "latest_image_price": 0,
        "oldest_image_price": 0,
        "oldest_time_jp": 0,
        "latest_time_jp": 0,
        "latest_price": 0,
        "oldest_price": 0,
        "latest_peak_price": 0,
        "oldest_peak_price": 0,
        "gap": 0.0001,
        "gap_high_low": 0.00001,
        "gap_close": 0.00001,
        "body_ave": 0.000001,
        "move_abs": 0.00001,
        "memo_time": 0,
        "latest2_dir": 0,  # 直近二つのローソクの方向を二桁であらわす.
        "skip_counter": 0,   # 南海スキップしたか
        "data": data_df,  # 対象となるデータフレーム（元のデータフレームではない）
        "data_remain": data_df,  # 対象以外の残りのデータフレーム
        "include_large": False,
        "include_very_large": False,
    }

    # 処理
    if len(data_df) < 1:  # ■異常処理。データが存在してい無ければ、仮のデータを入れて終了
        # 返却用（シンプルでデータフレームがないものを作成する）
        return ans_dic

    # 通常の処理
    base_direction = 0
    skip_counter = 0  # 各区間でスキップが何回起きたかをカウントする
    counter = 0
    skip_num = 1  # 変数として利用する値（スキップ指定）
    skip_num_always = 1   # SKIPNUMに代入して利用。初回以外はスキップ有で実行
    skip_num_first = 0  # SKIPNUMに代入して利用。初回のみスキップ無しで実行
    for i in range(len(data_df)-1):
        # 最新から古い方に１行ずつ検証するため、i+1が変化前（時系列的に前）。 i+1 ⇒ i への傾きを確認する（コード上はi→i+1の動き）
        tilt = data_df.iloc[i]['middle_price'] - data_df.iloc[i+1]['middle_price']
        # print("TILT検証", data_df.iloc[i]['middle_price'], data_df.iloc[i+1]['middle_price'], data_df.iloc[i]['time_jp'], data_df.iloc[i+1]['time_jp'])
        # print("  ⇒", tilt)
        if tilt == 0:
            tilt = 0.001
        tilt_direction = round(tilt / abs(tilt), 0)  # 方向のみ。（１かー１に変換する）（念のためラウンドしておく）
        # ■初回の場合の設定。１行目と２行目の変化率に関する情報を取得、セットする
        if counter == 0:
            base_direction = tilt_direction
        elif counter == 1:
            skip_num = skip_num_first  # 初回をスキップすると、折り返しが見抜けないことがある。counterは１の時。
        else:
            skip_num = skip_num_always

        # ■カウントを進めていく
        if tilt_direction == base_direction:  # 今回の検証変化率が、初回と動きの方向が同じ場合
            counter += 1
        else:
            # ■SKIPを考慮したうえで、skipしても成立するか確認する。
            # print(" 逆向き発生", data_df.iloc[i]['time_jp'] ,"から", data_df.iloc[i+1]['time_jp'])
            if i + 1 + skip_num >= len(data_df):
                # データフレームの数を超えてしまう場合はスキップ（データなしエラーになるため）
                break
            else:
                #
                #          〇の足が原因
                #     i+1  i    i-1
                #               ↑
                #      ↑   ↓    ↑
                #      ↑   ↓    ↑
                #   ↑      ↓    ↑
                #   ↑  　
                #   ↑
                #
                # [i]が方向転換のカギになっている為、[i]を飛ばして、[i-1]と[i+skip]で成立するかを確認。
                # ただしその場合、ターンに食い込む可能性あるため、
                # ここまでの傾きと、[i+skip]と[i+skip+1]の傾きが一致していればスキップ成立（１個１個で折り返す場合は、、、これでもダメかも)
                # ①SKIPでの傾き
                tilt_cal = data_df.iloc[i-1]['middle_price'] - data_df.iloc[i + skip_num]['middle_price']
                tilt_direction_skip = round(tilt_cal / abs(tilt_cal), 0) if tilt_cal != 0 else 0.001  # 傾きが継続判断基準
                # print("　　", data_df.iloc[i-1]['time_jp'], "(i-1)と", data_df.iloc[i + skip_num]['time_jp'], "でSKIP検証")
                # ②SKIP後の傾き（従来の傾きと同一でないといけない部分）
                tilt_cal_future = data_df.iloc[i + skip_num]['middle_price'] - data_df.iloc[i + skip_num + 1]['middle_price']
                tilt_direction_future = round(tilt_cal_future / abs(tilt_cal_future), 0) if tilt_cal_future != 0 else 0.001  # 傾きが継続判断基準
                # print("   ", data_df.iloc[i + skip_num]['time_jp'], "と", data_df.iloc[i + skip_num+1]['time_jp'], "でBase方向と比較")
                # ③厳しめ条件 SKIP部のPIP数が大きくても、折り返しを検出したい。
                # temp_str = ""
                # total_gap = 0
                # for skip_gap_i in range(skip_num):
                #     temp_str = temp_str + str(data_df.iloc[i + skip_gap_i]['time_jp']) + ","
                #     total_gap = total_gap + data_df.iloc[i + skip_gap_i]['body']
                # print("　　これの合計移動距離",total_gap, temp_str)
                # 判定処理　
                if tilt_direction_skip == base_direction and base_direction == tilt_direction_future:
                    # 規定数抜いてもなお、同方向の場合、スキップする
                    # print(" 　　--SKIP発生", data_df.iloc[i-1]['time_jp'], data_df.iloc[i + skip_num]['time_jp'])
                    counter = counter + skip_num
                    skip_counter = skip_counter + 1
                else:
                    break
            # break  # 連続が途切れた場合、ループを抜ける
    # ■対象のDFを取得し、情報を格納していく
    ans_df = data_df[0:counter+1]  # 同方向が続いてる範囲のデータを取得する
    ans_other_df = data_df[counter:]  # 残りのデータ

    if base_direction == 1:
        # 上り方向の場合、直近の最大価格をlatest_image価格として取得(latest価格とは異なる可能性あり）
        latest_image_price = ans_df.iloc[0]["inner_high"]
        oldest_image_price = ans_df.iloc[-1]["inner_low"]
        latest_peak_price = ans_df.iloc[0]["high"]
        oldest_peak_price = ans_df.iloc[-1]["low"]
    else:
        # 下り方向の場合
        latest_image_price = ans_df.iloc[0]["inner_low"]
        oldest_image_price = ans_df.iloc[-1]["inner_high"]
        latest_peak_price = ans_df.iloc[0]["low"]
        oldest_peak_price = ans_df.iloc[-1]["high"]
    #
    # ■平均移動距離等を考える
    body_ave = round(data_df["body_abs"].mean(),3)
    move_ave = round(data_df["moves"].mean(),3)

    # ■GAPを計算する（０の時は割る時とかに困るので、最低0.001にしておく）
    # gap = round(abs(latest_image_price - oldest_image_price), 3)  # MAXのサイズ感
    gap_close = round(abs(latest_image_price - ans_df.iloc[-1]["close"]), 3)  # 直近の価格（クローズの価格&向き不問）
    if gap_close == 0:
        gap_close = 0.001
    else:
        gap_close = gap_close

    gap = round(abs(latest_image_price - oldest_image_price), 3)  # 直近の価格（クローズの価格&向き不問）
    if gap == 0:
        gap = 0.001
    else:
        gap = gap

    gap_high_low = round(abs(latest_peak_price - oldest_peak_price), 3)  # 直近の価格（クローズの価格&向き不問）
    if gap_high_low == 0:
        gap_high_low = 0.001
    else:
        gap_high_low = gap_high_low

    body_pattern = 0
    if counter+1 == 2:
        # 直近のボディーの方向、
        if data_df.iloc[0]['body'] <= 0:
            # マイナスの場合、１０の位は１
            body_pattern = 10
        else:
            body_pattern = 20
        # 直近から２番目のボディーの方向
        if data_df.iloc[1]['body'] <= 0:
            # マイナスの場合、１の位は１
            body_pattern += 1
        else:
            body_pattern += 2

    # ■　一旦格納する
    # 表示等で利用する用（機能としては使わない
    memo_time = f.str_to_time_hms(ans_df.iloc[-1]["time_jp"]) + "_" + f.str_to_time_hms(
        ans_df.iloc[0]["time_jp"])
    # 返却用
    ans_dic = {
        "direction": base_direction,
        "count": counter+1,  # 最新時刻からスタートして同じ方向が何回続いているか
        "data_size": len(data_df),  # (注)元のデータサイズ
        "latest_image_price": latest_image_price,
        "oldest_image_price": oldest_image_price,
        "oldest_time_jp": ans_df.iloc[-1]["time_jp"],
        "latest_time_jp": ans_df.iloc[0]["time_jp"],
        "latest_price": ans_df.iloc[0]["close"],
        "oldest_price": ans_df.iloc[-1]["open"],
        "latest_peak_price": latest_peak_price,
        "oldest_peak_price": oldest_peak_price,
        "gap": gap,
        "gap_high_low": gap_high_low,
        "gap_close": gap_close,
        "body_ave": body_ave,
        "move_abs": move_ave,
        "memo_time": memo_time,
        "latest2_dir": body_pattern,
        "skip_counter": skip_counter,
        "data": ans_df,  # 対象となるデータフレーム（元のデータフレームではない）
        "data_remain": ans_other_df,  # 対象以外の残りのデータフレーム
    }

    # ■■　突発的な伸びを含むかを検証し、追記する
    ans_dic['include_large'] = check_large_body_in_peak(ans_dic)['include_large']
    ans_dic['include_very_large'] = check_large_body_in_peak(ans_dic)['include_very_large']
    ans_dic['highest'] = check_large_body_in_peak(ans_dic)['highest']
    ans_dic['lowest'] = check_large_body_in_peak(ans_dic)['lowest']

    # 返却する
    if f.dict_compare(ans_dic, ans_dic):
        return ans_dic
    else:
        print("★返却値異常")

