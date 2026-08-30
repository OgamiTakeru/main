<!-- 最新更新日時: 2026-08-29 12:43 JST -->
# flip_predict を classPositionControl のスロット管理へ統合する設計

作成: 2026-08-27 / 状態: **実装済み（2026-08-27）**

## 目的

flip_predict のライブ（`fFlipPredictLive.py`）は独自の状態機械でポジションを持っており、
`classPositionControl` のスロット外で建玉を保有している。ポジションは全て
`classPositionControl` のスロットで管理し、通貨ごとの保有数を一元的に数えられる
状態にしたい。

## 責務の分担（この設計の背骨）

- `classPosition` … **渡されたポジションを監視する**。flip 固有のロジックは持たない。
  ただし出自は保持し、flip 生まれと分かれば flip 側へ委譲する（＝逆算はできる）。
- flip 側のファイル … **オーダーを生む解析**。タッチ検出・観測・3モード判定を担う。
  「flip を直したいときは flip の名前のファイルを見ればよい」状態を保つ。

## 既存の受け皿（新規実装が不要な部分）

調査の結果、必要な仕組みはほぼ既存にあった。

| flip の要件 | 既存の受け皿 |
|---|---|
| オーダー発行前の待機を監視 | `classPosition.waiting_order` → `watching_for_position(candle)`（`classPosition.py:1658`）。`life=True` かつオーダー未発行という状態が既にある |
| +1.2R 到達で +1.05R へ損切り引き上げ | `lc_change`（`classPosition.py:2469`）。`[{"exe": True, "trigger": lc_pips*1.2, "ensure": lc_pips*1.05}]` で表現でき、**専用実装は不要** |
| 60分でクローズ | `TRADE_TIMEOUT_MIN_DEFAULT` |
| エントリー種別 MARKET/LIMIT/STOP | `OCreate.Order` の `type` |
| 発注の窓口 | `positions_control_class.order_class_add()` |

## 統合後の流れ

```
mode1（5分ごと）
  └─ count2 検出 → flip が候補ラインを決める
       └─ この時点でスロットを1枠確保（waiting_order=True で登録）

mode2（1秒ごと）
  └─ candleAnalysisClass.update_s5_df(0)
  └─ all_update_information(candleAnalysisClass)
       └─ 各スロット .update_information(candle)
            ├─ waiting_order → watching_for_position(candle)
            │     └─ origin == "flip" なら flip 側へ委譲（キャンドルを渡す）
            │          ① ラインへのタッチ検出
            │          ② タッチ後60秒の観測
            │          ③ 3モード判定 → 発注
            └─ 保有中 → 既存の監視 + lc_change（損切り引き上げ）
```

## 決定事項

- **スロット確保のタイミング**: ① 開始時（count2 検出時）に確保する。
  タッチが来ないまま期限切れになる間も1枠塞ぐが、「候補も含めて全てスロットで
  管理する」という思想に忠実で、既存の `waiting_order` の考え方とも一致する。
- **スロット上限**: flip 専用枠は設けず、15枠すべてを旧戦略と共用する。
- **通貨ごとの上限**: 通貨ごとに15。プロセスが通貨単位なので口座全体では
  最大45になるが、これは想定通り。
- **起動時の全リセット**: `main_exe` 起動時の `reset_all_position()` は
  むしろ望ましい挙動なので、そのままでよい。

## 注意点

- **スロット枯渇**: flip は①で枠を取り最大60分（`ORDER_WAIT_MINUTES`）保持する。
  5分ごとに count2 が出ると最大12枠が待機で埋まりうる。共用と決めたので、
  旧戦略が発注できない時間帯が生じる可能性がある。運用しながら要観察。
- **S5 の取得頻度**: flip は現在4秒間隔でS5を取得している。mode2 は1秒ループなので
  頻度は足りるが、`update_s5_df()` は API 呼び出しを伴うため回数の確認が必要。
- **他建玉に触らない保証**: 現行 flip は `OWNER_TAG` で自分の建玉のみ操作している。
  統合後は `classPosition` 側にフラグを持たせて同等の保証を維持する。

## 移行時に flip 側から消えるもの / 残るもの

消える（`classPosition`/`classPositionControl` が担う）:
発注API呼び出し、約定確認、保有中の監視、損切り引き上げ、ハードクローズ、
`StateStore` のポジション部分

残る（flip の責務）:
S5取得、タッチ検出、観測窓、3モード判定、`OCreate.Order` の生成

## 検証・リプレイへの影響（結論：影響しない）

依存は一方向で、研究パイプラインはライブを参照していない。

```
研究パイプライン（count2_flip_*.py）  ← import される側
        ↑
ライブ（fFlipPredictLive.py）が研究側の関数を import して使う
```

確認済みの事実:
- `count2_flip_*.py` は `fFlipPredictLive` を一切 import していない
- `count2_flip_*.py` は `classPosition` / `classPositionControl` を一切 import していない
- シミュレーションは `count2_flip_core.FlipPathInspector` が独自に行い、ライブのコードを通らない

したがって **ライブをどう作り替えても `test_kick_*_flip_predict.py` による
train/OOS 検証は今日と同じように動く**。

### ただし逆方向には注意が必要

ライブは研究側の関数を共有している:
`add_feature_buckets` / `select_top_condition_policy_candidates`（count2_flip_workflow）、
`count2_resistance_sweep` のライン再構築、`count2_flip_core` の各設定クラス。

**この共有が「検証したロジックと実際に動くロジックが一致している」唯一の保証**。
統合作業でライブを書き換える際、これらを独自実装に置き換えると検証結果が
実運用を反映しなくなる。共有は維持すること。

## 統合するか否かの検討経緯（2026-08-27 のやりとり）

### 出発点
「flip が `classPositionControl` の外でポジションを持っているのが気になる。
ポジションは全てスロットで統一したい」

### 途中で判明した事実
- `classPositionControl` は使われなくなっていない。旧戦略（`main_exe`）では現役。
- `OpposingPositionPolicy` は置き換えではなく、`classPositionControl` の**内部で
  呼ばれる部品**（`classPositionControl.py:9, 219, 1044`）。逆ポジがあるときの
  可否判定だけを担う、状態を持たないクラス。役割が異なるので競合していない。
- flip のライブは `classPosition` / `classPositionControl` / `classOrderCreate` を
  一切使わず、`classOanda` だけを直接叩いている。

### 15個制限についての確認
`max_position_num = 15` は `__init__` で15個のリストを作るだけの、
**プロセス内・通貨ペア単位**の制限。口座全体を問い合わせてはいない。
→ 通貨ごとに絞る運用意図なので、口座全体で最大45になるのは想定通りと確認。

### 「載せる」ではなく「生まれたオーダーを管理する」
表現の修正: flip を `classPosition` に載せるのではなく、
**flip はオーダーを生む側**で、生まれたオーダーを既存と同じくスロットが管理する。
旧戦略（`fAnalysis_order_Main` → `order_class_add`）と同じ形。

### 委譲方式の採用
`classPosition` は flip の中身を知らないが、出自は保持し、
flip 生まれなら flip 側の監視を叩いて情報を得る（キャンドルデータを渡す）。
これにより「ポジションは全てスロット」「flip を直すときは flip のファイルを見る」
の両立ができる。

### 却下した案
- **flip の状態機械を `classPosition` のフィールドに載せ替える案**:
  `classPosition` の責務（ポジションの監視）を超えるため却下。
- **flip 専用スロット枠を切る案**: 上限は設けず15枠共用と決定。

## 着手前の前提

EUR_USD と AUD_USD が `LIVE = True` で稼働中。統合作業中は停止が必要。
`fFlipPredictLive.py` は約1700行あり、書き換え規模は大きい。


---

# 実装結果（2026-08-27）

## 作ったもの

| ファイル | 役割 |
|---|---|
| `classOrderCreate.Order` | `origin` / `owner_tag` を追加。省略時は従来どおり |
| `classPosition` | 同じ2つを保持。**中身は解釈しない** |
| `classPosition.ORIGIN_WATCH_HANDLERS` | 出自ごとの待機ハンドラ登録先。二重登録は拒否 |
| `classPosition.watching_for_position` | `origin` があれば委譲。未登録なら**何もせず待機** |
| `fFlipWatch.py`（新規） | flip の見張り本体。タッチ検出 → 60秒観測 → 3モード判定 → 発注 |
| `fFlipOrder.py`（新規） | flip シグナル → `OCreate.Order` の橋渡し |
| `main_exe.py` | ループ、共通時刻、CandleAnalysis生成、解析呼び出し、注文登録を担当 |
| `fAnalysis_order_Main.py` | `ANALYSIS_REGISTRY`で有効モード・固有実行条件・runnerを管理し、解析結果を統合 |
| `main_exe_euro.py` / `main_exe_aud.py` | `fFlipPredictLive.run_live` から `main_exe.run` へ移行 |
| `test_flip_position_integration.py`（新規） | 13件、全通過 |

## 現在の設定

- `inspection`: ライン解析
- `live`: flip解析
- flip固有の5分境界・6〜29秒判定は解析登録側で管理

## 実装中に判明した制約と対処

- **共有 S5 は 5 本（25秒）しかない**: `update_s5_df` は `count: 5` で取得しており、
  観測窓の 60 秒（12本）に足りない。共有側を変えると旧戦略にも影響するため、
  `fFlipWatch` 側で受信バーを時刻の重複排除をしながら貯める方式にした。
  mode2 は 2 秒ごとに回り 1 回の取得が 25 秒を覆うので欠損は生じない。
  観測窓に欠損があれば判定せず待機する保護も入れてある。
- **クロス通貨の units 計算に USD/JPY レートが要る**: `gene.calculate_units` が
  要求する。`fFlipOrder.usd_jpy_rate_for` で取得し、失敗時は既定値 160.0 に
  落として注文自体は落とさない（`fLineAnalysis` と同じ考え方）。
- **損切り引き上げは新規実装が不要だった**: 既存 `lc_change` の
  `{"trigger": ..., "ensure": ...}` がそのまま「+1.2R で発動し +1.05R を確保」を
  表せる。LC 10pips なら trigger 12.0p / ensure 10.5p に翻訳される（テスト済み）。

## 既存テストの状況（今回の変更とは無関係）

`test_predict_reversal_order`（8件）と `test_opposing_position_policy`（3件）は
**変更前から失敗している**。変更を退避して実行しても同じ結果になることを確認済み。

## 残作業・要観察

- 実運用での動作確認はまだ。次回起動時から新しい経路になる。
- `fFlipPredictLive.py` は `build_live_signal` と `bind_policy` を提供する
  ライブラリとして残っている。`run_live` は使われなくなったが、削除は
  動作確認後にする。
- スロット枯渇（flip の待機が最大12枠を占める可能性）は運用しながら要観察。


---

# レビュー指摘への対応（2026-08-27）

外部レビューで 10 件の指摘を受け、コードで裏を取りながら対応した。
**指摘はすべて事実だった。**特に 1 番は自作テストが偽オブジェクトを使っていた
ために自力では気づけない構造だった。

## 修正した項目

| # | 内容 | 対応 |
|---|---|---|
| 1 | **即発注（致命）** | `fFlipOrder` に `order_permission=False` が無く、`classPosition.py:599` で登録した瞬間に発注されていた。見張りが一度も動かない状態。修正し、**実登録経路を通るテストで、外すと失敗することを実証** |
| 2 | 早期決済 | 待機注文は判定を発注時まで持ち越す。さらに所有タグ付き建玉を保護（下記） |
| 3 | owner tag | プラン辞書に持つだけで実 API に付いていなかった。`clientExtensions` / `tradeClientExtensions` に付与し、`positionFill: OPEN_ONLY` も設定 |
| 4 | 60分決済 | **検証データで必須と確認**。`origin` を持つ注文限定で `trade_timeout_hard_close` を有効化 |
| 6 | MARKET時の基準 | 7 番の修正で解消（ライン価格の指値のままなので建値と TP/LC が一致） |
| 7 | 検証との不一致 | **3モード分岐は検証で赤字だった**（下記）。削除して検証と同じ経路に |
| 8 | 待機の永久残留 | 既存 `order_timeout` は発注済み注文専用で待機に届いていなかった。明示的な待機タイムアウトを追加。`reset()` で `flip_watch_state` も掃除 |

## 60分決済が必須である根拠（OOS 実測）

| ペア | 時間切れ決済 | それ以外 |
|---|---|---|
| AUD_USD | n=13 勝率69.2% **+140円** | +131円 |
| EUR_USD | n=9 勝率77.8% **+118円** | +2.5円 |

EUR_USD は時間切れ決済が利益のほぼ全て（全体 +121円）。この機構が無いと黒字が消える。

## 3モード分岐は実装しないのが正解（OOS 実測）

| 方式 | AUD_USD | EUR_USD |
|---|---|---|
| **current_first_touch_reversal**（タッチ→即指値） | 勝率52.9% PF1.25 **+271円** | 勝率50.0% PF1.10 **+121円** |
| three_branch_watch_entry（60秒観測＋3モード） | 勝率42.9% PF0.90 **-107円** | 勝率39.5% PF0.78 **-223円** |

両ペアとも 3 モードは赤字。旧ライブが `line_holding_only: True` で封じていたのも
正しかった。**60秒観測と3モード分岐は実装しない**（将来やるなら先に検証する）。

## 「他の注文から触られない」の実装

所有タグ付き建玉は、それを出した解析が自分の決済条件（TP/LC・損切り引き上げ・
60分）で最後まで面倒を見る前提。他の注文の都合で決済されると前提が崩れるので、
両建てのまま並走させる。塞いだ経路は 2 つ:

- `OpposingPositionPolicy.evaluate` … タグ付きは逆ポジとして数えない
- `classPositionControl.close_hedge_positions` … タグ付きスロットは対象外

タグ無しの建玉に対する既存の挙動は変えていない。

## 見送った指摘

- **5 起動時キャンセルが口座全体**: 変更が大きいためタスク保留。
  `OrderCancel_All_exe`（`classOanda.py:700`）は通貨も owner も絞らず、
  STOP_LOSS / TAKE_PROFIT 以外の全 PENDING を取り消す。EUR を再起動すると
  AUD や手動注文の指値も消える。
- **9 二重起動耐性**: 起動する IDE を固定しているため不要と判断。
  旧 flip には `SingleInstanceLock`（OS ファイルロック）、永続 StateStore、
  `recent_signal_ids`、owner 付き建玉の復元（`reconcile`）があったが、
  `main_exe` には元々無く、旧戦略と同水準。
- **10 close_trade の life 先行**: `classPosition.py:1225` で決済 API を呼ぶ
  **前に** `life_set(False)` している（コメント上、意図的）。API が失敗すると
  実建玉は残るのにプログラム上は消えた扱いになり、以後 60 分決済も呼ばれない。
  flip は 60 分決済が成績の中核なので影響が大きい。ただし単純に「失敗したら
  life を戻す」にすると、決済が通っているのに通信だけ失敗した場合にスロットが
  永久に埋まる。建玉の実在を API で確認してから判断するリトライ設計が要り、
  全戦略に影響するため別途扱う。

# 「常に1つだけ」— 実測して制限を採用（2026-08-28 決着）

検証（`count2_flip_workflow.replay_condition` の `locked_until`）は、待機中
または保有中の一件が片付くまで後続のシグナルを見送っていた。**flip は常に
1 つだけ**という前提で +271円 / +121円 が出ている。

「取引機会を増やしたい」という意図で一度は並行を選んだが、見送っていたぶんを
取ったらどうなるかを実測したところ、**全ペア・全期間で並行のほうが悪かった**。

`replay_condition(..., one_at_a_time=False)` で測定（`count2_flip_parallel_check.py`）:

| ペア | 期間 | 1つだけ | 全部取る |
|---|---|---|---|
| AUD_USD | train | n=79 PF1.68 **+857** | n=107 PF1.41 +786 |
| AUD_USD | **OOS** | n=51 PF1.25 **+271** | n=74 PF1.04 **+68** |
| EUR_USD | train | n=137 PF1.47 **+1287** | n=170 PF1.36 +1247 |
| EUR_USD | **OOS** | n=50 PF1.10 **+121** | n=66 PF1.05 +71 |
| USD_JPY | train | n=54 PF1.72 **+759** | n=57 PF1.62 +711 |
| USD_JPY | OOS | n=19 PF0.86 -71 | 同左（見送り1件のみ） |

追加された取引の質: AUD_USD は 23 件増えて -203円（1件あたり **-8.8円**）、
EUR_USD は 16 件増えて -50円（**-3.1円**）。**見送られていたシグナルは平均して
損を生む**。

理由は構造的なもの。見送られるのは「既存の注文が待機中・保有中に出たシグナル」
＝同じ値動きの途中で出た重複シグナルが多く、1 件目が既に良い位置を取っている
ぶん、2 件目は動いた後の不利な位置から入ることになる。

**採用**: `fFlipOrder.has_active_flip` で、flip 起点の待機注文または建玉が
一つでもあれば新しいシグナルを作らない。検証と同じ挙動。

# 再起動後の復元（2026-08-28）

プロセスを止めるとメモリ上の `origin` は消える。復元しないと、再起動後に
flip の建玉が「出自不明」となり、**保護も 60 分決済も「1つだけ」制限も全て
外れる**。

OANDA 側の `clientExtensions.tag` は建玉に残るので、そこから復元する。

- `classPosition.ORIGIN_BY_OWNER_TAG` … タグ→出自の対応表
- `fFlipWatch` が `APPROVED_PAIRS` のタグを起動時に登録
- `catch_exist_position` がタグを読んで `origin` / `owner_tag` を戻す

## 復元されるもの / されないもの

| 情報 | 復元元 |
|---|---|
| 利確・損切り価格 | OANDA の `takeProfitOrder` / `stopLossOrder`（引き上げ済みの値も） |
| 建値・数量・方向 | 建玉そのもの |
| 約定時刻・経過時間 | `openTime`（60分決済が再起動後も効く） |
| **flip 起点かどうか** | **`clientExtensions.tag`（今回追加）** |
| `lc_change` の予定 | ❌ 復元しない |
| 待機中の注文 | ❌ OANDA に存在しないため原理的に不可 |

`lc_change` を復元しない判断: TP/SL はブローカー側で生きているため、最悪でも
当初の TP/LC で決済される。失われるのは「引き上げによる上振れ」だけで、
想定外の損失にはならない。`comment` への書き込みと読み戻しを両方保守する
複雑さに見合わないと判断した。

`tag` の上限は 128 文字（[ClientTag 仕様](https://oanda-api-v20.readthedocs.io/en/latest/types/ClientTag.html)）。
今は `flip_predict_aud` のような分類名だけを入れている。

# 起動時キャンセルの通貨限定（2026-08-28 完了・旧タスク5）

`OrderCancel_All_exe(pair=None)` と `OrdersWaitPending_exe(pair=None)` に
省略可能な通貨引数を追加。省略時は従来どおり口座全体なので既存の呼び出しは
影響を受けない。`reset_all_position`（2箇所）と
`refresh_startup_safety_state` が自分の担当通貨を渡すようにした。

- EUR_USD を再起動しても AUD_USD や手動注文の指値は消えない
- `refresh_startup_safety_state` も絞った。絞らないと他通貨の注文が残っている
  せいで安全状態へ戻れず、新規注文が止まり続ける
- `instrument` 列が取れない場合、通貨指定時は**何もキャンセルしない**
  （絞れないまま実行して他通貨まで消すより安全）

# close_trade の life 先行を修正（2026-08-28 完了・旧タスク10）

`classPosition.close_trade` は決済 API を呼ぶ**前**に `life_set(False)` して
いた。API が失敗すると実建玉は残るのにプログラム上は消えた扱いになり、
以後 60 分決済も呼ばれない。

単純に順序を入れ替えると、逆に「決済は通ったが応答だけ失われた」場合に
スロットが永久に埋まる。どちらの事故も避けるため、失敗時に
`trade_is_still_open_after_failed_close` で建玉の実在を確認してから決める:

| 確認結果 | life |
|---|---|
| まだ OPEN | 維持（次の巡回で再試行） |
| すでに CLOSED | 解放（決済は成立していた） |
| 確認自体が失敗 | 維持（安全側。残っている前提） |

部分決済のフォールバック分岐（units 過大で全解除に切り替わる箇所）にも同じ
問題があったので併せて修正。

# 残タスク

- **USD_JPY の改善**: ローソク形状系の特徴量を除外して再探索する案。
  USD_JPY は上位条件が fc2 のヒゲ・押し戻しに偏り、train は良いが OOS で
  崩れる（PF 1.72 → 0.86）。AUD/EUR は「ラインの構造」を捉えており対照的。
- **両建てで損切りを建値へ**: 検証に両建ての挙動が含まれていないため、
  どちらが良いかを示すデータが無い。やるなら検証の仕組みから作る必要がある。
- **3モード分岐（60秒観測）**: 検証では赤字（AUD -107円 / EUR -223円）。
  実装しないのが正解。将来やるなら先に検証する。
- **実運用での動作確認**: 統合後の経路はまだ実弾で動かしていない。
  次回起動時から新経路になるので、最初はログを確認すること。
