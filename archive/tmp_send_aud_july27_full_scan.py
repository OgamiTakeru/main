import send_notice as notice


notice.line_send(
    "inspection AUD/USD 7/27 0:00-23:55全走査（厳格化後）\n"
    "5分刻み、判断時点以前の情報のみで生成、後続S5で評価。\n"
    "厳格immediate breakout: 6件、4勝2敗、+7.6p。\n"
    "勝ち: 13:00/13:05 upper 各+4.6p、20:05/20:10 lower 各+4.6p。\n"
    "負け: 18:40/18:45 upper 各-5.4p。5分重複を1セット化すると2勝1敗+3.8p。\n"
    "負け共通: h1_path_ahead_1_distance=0.2-0.4p。"
    "勝ちは1.5p、4.4-4.8p。事前にpath clearance>=1.0pを必須化すると、"
    "当日は重複込み4勝0敗+18.4p、セット化2勝0敗+9.2p。\n"
    "一方limit/STOP breakoutは25決済10勝15敗-25.9p。"
    "現行のAUD厳格化はimmediateのみなので、limit breakout側は別途対策候補。\n"
    "単日逆算のため、path clearance 1pは1年WF検証必須。"
)
