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
        "peak_time": 0,  # ピーク時刻（重複するが、わかりやすい名前で持っておく）
        "peak": 0,  # ピーク価格（重複するが、わかりやすい名前で持っておく）
        "latest_time_jp": 0,  # これがpeakの時刻
        "oldest_time_jp": 0,
        "direction": 1,
        "strength": 0,  # この関数では付与されない（単品では判断できない）。make_peaks関数で前後のPeakを加味して付与される
        "count": 0,  # 最新時刻からスタートして同じ方向が何回続いているか
        "data_size": len(data_df),  # (注)元のデータサイズ
        "latest_body_peak_price": 0,  # これがpeakの価格
        "oldest_body_peak_price": 0,
        "latest_wick_peak_price": 0,
        "oldest_wick_peak_price": 0,
        "latest_price": 0,
        "oldest_price": 0,
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
        "include_very_large": False,
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
        latest_body_price = ans_df.iloc[0]["inner_high"]
        oldest_body_price = ans_df.iloc[-1]["inner_low"]
        latest_wick_price = ans_df.iloc[0]["high"]
        oldest_wick_price = ans_df.iloc[-1]["low"]
    else:
        # 下り方向の場合
        latest_body_price = ans_df.iloc[0]["inner_low"]
        oldest_body_price = ans_df.iloc[-1]["inner_high"]
        latest_wick_price = ans_df.iloc[0]["low"]
        oldest_wick_price = ans_df.iloc[-1]["high"]
    #
    # ■平均移動距離等を考える
    body_ave = round(data_df["body_abs"].mean(),3)
    move_ave = round(data_df["moves"].mean(),3)

    # ■GAPを計算する（０の時は割る時とかに困るので、最低0.001にしておく）
    # gap = round(abs(latest_body_price - oldest_body_price), 3)  # MAXのサイズ感
    gap_close = round(abs(latest_body_price - ans_df.iloc[-1]["close"]), 3)  # 直近の価格（クローズの価格&向き不問）
    if gap_close == 0:
        gap_close = 0.001
    else:
        gap_close = gap_close

    gap = round(abs(latest_body_price - oldest_body_price), 3)  # 直近の価格（クローズの価格&向き不問）
    if gap == 0:
        gap = 0.001
    else:
        gap = gap

    gap_high_low = round(abs(latest_wick_price - oldest_wick_price), 3)  # 直近の価格（クローズの価格&向き不問）
    if gap_high_low == 0:
        gap_high_low = 0.001
    else:
        gap_high_low = gap_high_low

    # ■　返却用にans_dicを上書き
    ans_dic['direction'] = base_direction
    ans_dic["count"] = counter + 1  # 最新時刻からスタートして同じ方向が何回続いているか
    ans_dic["data_size"] = len(data_df)  # (注)元のデータサイズ
    ans_dic["latest_body_peak_price"] = latest_body_price
    ans_dic["oldest_body_peak_price"] = oldest_body_price
    ans_dic["oldest_time_jp"] = ans_df.iloc[-1]["time_jp"]
    ans_dic["latest_time_jp"] = ans_df.iloc[0]["time_jp"]  # これがピークの時刻
    ans_dic["latest_price"] = ans_df.iloc[0]["close"]  # これがピークの価格
    ans_dic["oldest_price"] = ans_df.iloc[-1]["open"]
    ans_dic["latest_wick_peak_price"] = latest_wick_price
    ans_dic["oldest_wick_peak_price"] = oldest_wick_price
    ans_dic["peak_time"] = ans_dic["latest_time_jp"]  # 重複するが、わかりやすい名前で持っておく
    ans_dic["peak"] = ans_dic["latest_price"]  # 重複するが、わかりやすい名前で持っておく
    ans_dic["gap"] = gap
    ans_dic["gap_high_low"] = gap_high_low
    ans_dic["gap_close"] = gap_close
    ans_dic["body_ave"] = body_ave
    ans_dic["move_abs"] = move_ave
    ans_dic["data"] = ans_df  # 対象となるデータフレーム（元のデータフレームではない）
    ans_dic["data_remain"] = ans_other_df  # 対象以外の残りのデータフレーム
    ans_dic["memo_time"] = f.str_to_time_hms(ans_df.iloc[-1]["time_jp"]) + "_" + f.str_to_time_hms(
        ans_df.iloc[0]["time_jp"])  # 表示に利用する時刻表示用
    ans_dic["strength"] = 0  # 念のために入れておく
    # 追加項目
    ans_dic['include_large'] = check_large_body_in_peak(ans_dic)['include_large']
    ans_dic['include_very_large'] = check_large_body_in_peak(ans_dic)['include_very_large']
    ans_dic['highest'] = check_large_body_in_peak(ans_dic)['highest']
    ans_dic['lowest'] = check_large_body_in_peak(ans_dic)['lowest']

    # テスト表示用
    # print("BlockInspection")
    # for_print = {
    #     "oldest_time_jp": ans_df.iloc[-1]["time_jp"],
    #     "latest_time_jp": ans_df.iloc[0]["time_jp"],
    #     "direction": base_direction,
    #     "count": counter+1,  # 最新時刻からスタートして同じ方向が何回続いているか
    #     "data_size": len(data_df),  # (注)元のデータサイズ
    #     "latest_body_price": latest_body_price,
    #     "oldest_body_price": oldest_body_price,
    #     "latest_price": ans_df.iloc[0]["close"],
    #     "oldest_price": ans_df.iloc[-1]["open"],
    #     "latest_wick_price": latest_wick_price,
    #     "oldest_wick_price": oldest_wick_price,
    #     "gap": gap,
    #     "gap_high_low": gap_high_low,
    #     "gap_close": gap_close,
    #     "body_ave": body_ave,
    #     "move_abs": move_ave
    # }
    # print(for_print)

    # 返却する
    return ans_dic


def make_peaks(*args):
    """
    リバースされたデータフレーム（直近が上）から、ピークを一覧にして返却する
    :return:
    """
    # ■引数の整理
    # 基本検索と同様、最初の一つは除外する
    df_r = args[0]  # 引数からデータフレームを受け取る
    df_r = df_r[1:]  # 先頭は省く（数秒分の足のため）
    # ループの場合時間がかかるので、何個のPeakを取得するかを決定する(引数で指定されている場合は引数から受け取る）
    if len(args) == 2:
        max_peak_num = args[1]
    else:
        max_peak_num = 15  # N個のピークを取得する

    # ■処理の開始
    peaks = []  # 結果格納用
    next_time_peak = {}  # 処理的に次（時間的には後）のピークとして保管
    for i in range(222):
        if len(df_r) == 0:
            break
        # ■ピークの取得
        this_peak = make_peak(df_r)

        # ■ループ終了処理　ループ終了、または、 重複対策（←原因不明なので、とりあえず入れておく）
        if len(peaks) != 0 and peaks[-1]['latest_time_jp'] == this_peak['latest_time_jp']:
            # 最後が何故か重複しまくる！時間がかぶったら何もせず終了
            break
        elif len(peaks) > max_peak_num:
            # 終了（ピーク数検索数が上限に到達した場合）
            break

        # ■実処理の追加(前後関係の追加）
        # peakの簡素化
        this_peak.pop('data', None)  # DataFrameを削除する# 存在しない場合はエラーを防ぐためにデフォルト値を指定
        this_peak.pop('data_remain', None)  # DataFrameを削除する
        # peakのコピーを生成（PreviousやNextがない状態）
        this_peak_simple_copy = this_peak.copy()  # 処理的に次（時間的には後）のピークとして保管
        # 後ピークの追加（時間的に後）
        this_peak['next_time_peak'] = next_time_peak
        next_time_peak = this_peak_simple_copy  # 処理的に次（時間的には後）のピークとして保管
        # 前関係の追加 (現在処理⇒Peak,ひとつ前の処理（時間的には次）はpeaks[-1])
        if i != 0:
            # 先頭以外の時(next_timeはある状態。previousは次の処理で取得される）。先頭の時は実施しない。
            peaks[-1]['previous_time_peak'] = this_peak_simple_copy  # next_timeのpreviousに今回のpeakを追加
        # 結果を追加
        peaks.append(this_peak)  # 情報の蓄積

        # ■ループ処理
        df_r = df_r[this_peak['count']-1:]  # 処理データフレームを次に進める

    # ■ピークの強さを付与する(1,2,3の3段階。３が最も強い）
    for i, item in enumerate(peaks):
        # ほとんどスキップと同じ感じだが、Gapが0.05以下の場合は問答無用で低ランク
        # Gapがクリアしても、両側に比べて小さい場合、低ランク
        if i == 0 or i == len(peaks)-1:
            print("最初か最後のため、Vanish候補ではない", i)
            continue

        # わかりやすく命名 （vanish_itemは中央のアイテムを示す）
        latest_item = peaks[i-1]
        oldest_merged_item = peaks[i+1]

        #
        gap_border = 0.05
        gap_border_second = 0.08
        count_border = 2
        if item['gap'] <= gap_border or (item['gap'] <= gap_border_second and item['count'] <= count_border):
            # このアイテムのGapが小さい場合、直前も低くなる事に注意
            item['strength'] = 1  # これで元データ入れ替えられるんだ？！
            peaks[i+1]['strength'] = 1  # ひとつ前(時間的はOldest）のPeakも強制的にStrengthが1となる

    return peaks


def skip_peaks(peaks):
    """
    peaksを受け取り、必要に応じてスキップする
    """
    s4 = "    "
    print(s4, "SKIP Peaks")
    # for vanish_num, vanish_item in enumerate(peaks):
    adjuster = 0
    for i in range(len(peaks)):  # 中で配列を買い替えるため、for i in peaksは使えない！！
        vanish_num = i + adjuster  # 削除後に、それを起点にもう一度削除処理ができる
        if vanish_num == 0 or vanish_num > len(peaks)-1:
            print("最初か最後のため、Vanish候補ではない", vanish_num)
            continue

        print(vanish_num, adjuster, len(peaks))

        # わかりやすく命名 （vanish_itemは中央のアイテムを示す）
        latest_num = vanish_num - 1
        latest_item = peaks[latest_num]
        oldest_merged_num = vanish_num + 1
        oldest_merged_item = peaks[oldest_merged_num]
        vanish_item = peaks[vanish_num]

        # ■スキップ判定 (vanishは真ん中のPeakを意味する）
        # (0)スキップフラグの設定
        is_skip = False
        # (1)基本判定 サイズが小さいときが対象
        count_border = 3
        gap_border = 0.045
        if vanish_item['count'] <= count_border and vanish_item['gap'] <= gap_border:
            pass
        else:
            # そこそこサイズがあるので、スキップ
            continue

        # (2)ラップ判定
        # 変数の設定
        vanish_latest_ratio = vanish_item['gap'] / latest_item['gap']
        vanish_oldest_ratio = vanish_item['gap'] / oldest_merged_item['gap']
        # 判定１
        overlap_ratio = 0.7  # ラップ率のボーダー値　(0.7以上でラップ大。0.7以下でラップ小）
        if vanish_latest_ratio >= overlap_ratio and vanish_oldest_ratio >= overlap_ratio:
            # 両サイドが同じ程度のサイズ感の場合、レンジ感があるため、スキップはしない（ほとんどラップしている状態）
            print(s4, s4, "スキップ無し", latest_item['gap'], latest_item['gap'], oldest_merged_item['gap'])
            continue
        # 判定２
        peak_gap_border = 0.05
        if vanish_item['gap'] <= peak_gap_border:
            if vanish_latest_ratio <= overlap_ratio and vanish_oldest_ratio <= overlap_ratio:
                print(s4, s4, "Gap小かつ微妙な折り返し", vanish_item['gap'], vanish_latest_ratio, vanish_oldest_ratio)
                is_skip = True

        # ■スキップ処理
        if is_skip:
            print(" 結合処理", vanish_item)
            # oldestに情報を集約（midはCount以外はなかったと同様、latestはOldestの'latest系'に転記される）
            peaks[oldest_merged_num]['latest_body_peak_price'] = latest_item['latest_body_peak_price']
            peaks[oldest_merged_num]['latest_time_jp'] = latest_item['latest_time_jp']
            peaks[oldest_merged_num]['latest_price'] = latest_item['latest_price']
            peaks[oldest_merged_num]['peak_time'] = latest_item['peak_time']
            peaks[oldest_merged_num]['peak'] = latest_item['peak']
            peaks[oldest_merged_num]['count'] = (latest_item['count'] + vanish_item['count'] +
                                                 oldest_merged_item['count'])-2
            peaks[oldest_merged_num]['next_time_peak'] = latest_item['next_time_peak']
            peaks[oldest_merged_num]['gap'] = round(abs(oldest_merged_item['latest_body_peak_price'] -
                                                    oldest_merged_item['oldest_body_peak_price']), 3)
            peaks[oldest_merged_num]['strength'] = 0  # 従来はlatest_item['strength']だが、結合＝０にした方がよい場合が、、
            # 情報を吸い取った後、latestおよびmidは削除する
            del peaks[latest_num:oldest_merged_num]
            adjuster = -1
        else:
            adjuster = 0

    return peaks


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

