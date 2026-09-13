# リポジトリ整理のタスク

解析や戦略ではなく、ファイル配置・容量などの整理仕事をここに置く。
どれも急がないが、放置すると探しにくくなる類のもの。

---

## H1. `test_*.py` を `main/test/` へ移す

### 背景

`main` 直下の `test_*.py` が **218本**まで増え、他のソースに紛れて
目的のファイルを探しにくくなった。ユーザーの指示：

> 今後testはmainの中のtestフォルダに作ってね。数が増えすぎたから。
> ただキックもtestのうちだからtestに入れたい

**キック（検証スイープの起動ファイル）もテストの一種として扱い、
回帰テストと同じ `main/test/` に置く。**別フォルダに分けない。

### 対象

| 種類 | 本数 | 中身 |
|---|---:|---|
| 回帰テスト | 204本 | `unittest` で動かすもの |
| キック | 14本 | `python test_kick_xxx.py` で直接叩く起動ファイル |
| 合計 | 218本 | |

キック14本の内訳：

```
抵抗線ブレイク      6本  test_kick_{aud_usd,eur_usd,usd_jpy}_resistance_break{,_2y}.py
フリップ            3本  test_kick_{aud_usd,eur_usd,usd_jpy}_flip_predict.py
ダブルトップ        4本  test_kick_{all_pairs,aud_usd,eur_usd,usd_jpy}_double_top.py
抵抗線の監視        1本  test_kick_resistance_watch.py
```

### 移すと壊れるもの

キックは全て `main` 直下のモジュールを**絶対インポート**している。

```python
from count2_resistance_sweep import main          # 抵抗線 6本
from count2_flip_pipeline import ...              # フリップ 3本
from double_top_grid_validation import ...        # ダブルトップ 4本
from resistance_live_monitor import ...           # 1本
```

`python test/test_kick_xxx.py` として実行すると、Python が `sys.path` に
加えるのは**スクリプトのある `main/test/`** であって `main` ではない。
そのため `count2_resistance_sweep` が見つからず ImportError になる。

### 方針：案A（各ファイルの冒頭に2行足す）

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from count2_resistance_sweep import main
```

実行方法は今までどおり `python test/test_kick_xxx.py` のままで、
引数なしでそのまま叩ける形（起動ファイルの方針）を保てる。

**採らなかった案B**：`python -m test.test_kick_xxx` で実行する形。
ファイルを触らずに済むが `main/test/__init__.py` が必要で、
起動が引数付きのコマンドになるため、起動ファイルの方針と合わない。

### 未決

- 回帰テスト204本も同時に移すか。こちらは `unittest` で動かしているので、
  発見のされ方（`python -m unittest test.xxx` になる等）が変わる。
  移す前に現在の実行方法を確認すること。
- `test_kick_resistance_watch.py` は `resistance_live_monitor.py` を呼ぶ。
  この監視ツールは本番口座へ直接発注する危険な別系統として**起動禁止**に
  なっているので、移動のついでに扱いを決める（削除も選択肢）。

### 状態

**保留。**ユーザーの指示：「キックの件はタスクとして教えて、後で。」
実施の指示があるまで着手しない。

---

## H2. ディスクの整理（保留）

最大 127GB が回収可能と見積もった。段階を分けて確認済み。

- 段1：`過去/cache_*.pkl` 約45.7GB。コード上 `.pkl` を読む箇所は無い
- 段2：`count2_target_grid_*` の旧世代 約51GB

**保留。**削除は不可逆なので、実施前に対象一覧を出して確認する。

---

## H3. コメントと実装のずれ（保留）

走行や成績には影響しないが、読むと誤解する箇所。

- `classPositionControl.py:1075-1082` — `deferred_until_order` が
  設定されるだけで読まれていない
- `fFlipOrder.py:141-146` — 優先度 10/20/30 が全部同じ帯に落ちる旨が
  コメントと合っていない

**保留。**
