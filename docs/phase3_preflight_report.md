# Phase 3 input preflight

実測日: 2026-09-22。調査対象は原則2017-01-01以降。
Raw/Canonical・旧DB・旧保全資産への変更は行わない。
Rating、motor A/B、Prediction、3連単確率、odds予測、value、Betting、
2026 walk-forward本体は実装していない。

## A. Verdict

**Phase 2.5 checkpointのpush完了・local/remote一致を確認済み**。
データpreflight自体は **PREFLIGHT_PASS_WITH_LIMITATIONS**。
入力sourceと異常分布を調査したが、歴史的公開時点・特殊結果の学習採否・
実snapshot timestampの証拠に未解決事項がある。
oddsのfinal/5-minute分類は最新のユーザー確認により確定した。
モデル利用を一括承認する判定ではない。
checkpointのremote確認と調査結果は別々に判定する。

## B. Phase 2.5 checkpoint

- Branch: `main`
- Commit: `d902ff2f2a965d0e50a33b6a4598580bb95b7d0a`
- Message: `Checkpoint verified 2017+ history foundation`
- 指定12ファイルのみ、2,397 insertions / 2 deletions。
- commit直後working tree: clean。
- 62 tests PASS / 0 failures / 0 skipsを今回再実行。使い捨てDBでの実source小範囲pipeline・冪等性もPASS。
- migration 0001/0002を空DBで再適用し、現DBとのschema signature一致を確認。
  `0b0abc6e1f5abc9f5997a9c28a0f8067864594dd9bce5a1a52311b82062fd828`
- 独立read-onlyレビュー: BLOCKINGなし、具体的な追加指摘なし。
- secrets候補0、binary/巨大生成物混入0、diff whitespace問題0。
- 現DBの7 Canonical table件数、Raw batch 656 / row_count合計8,567,684、
  race期間2017-01-01〜2026-09-19、pre-2017 Canonical 0、F/L数値ST 0、
  既存Phase 2 dataset 1/2のhash不変を直接確認。
- 保存済み全件監査・117月replay・484 batch hash/119 dataset hash証跡を確認。
  今回、全件監査を再起動したが、前回実行が約40分であることを確認し、
  必須範囲の直接照合へ切り替えるため途中停止した。
  **全件監査・全件replayを今回再完了したという主張ではない。**
- 証跡: `.local/phase25/checkpoint_tests.json`, `checkpoint_verification.json`。
  `checkpoint_audit.json`は中断による空ファイルであり成功証跡ではない。
- 既存の `phase25_report.md` のGit節はcheckpoint前の履歴記録として保持。

Push状態（2026-09-22 checkpoint確定前の再確認）: push完了。
local HEAD、remote-tracking `origin/main`、GitHub実remote `refs/heads/main`は
すべて `d902ff2f2a965d0e50a33b6a4598580bb95b7d0a` で一致。
既存originは `https://github.com/yonsei50-cyber/boatrace-predictor.git`。
以前のpush承認待ちは解消済み。今回のpreflightは独立checkpointとして確定する。

## C. 全国勝率

**ユーザー訂正を適用**: 「期別」は要件ではなく、
`pckyotei.public.brd_l3.zenkoku_ritsu_1` を正式な主入力として優先採用する。
意味は選手の競走点平均であり、1着率ではない。
同じ5.xx形式でも `brd_ki.ritsu_1` は別の算出期間を持つ補助参照で、
L3欠測時にKIで自動補完する規則は設けない。今回は値の採用実装・motor計算は行っていない。

|項目|KI 期別成績|L3 出走表全国成績|
|---|---|---|
|field|`ritsu_1`|`zenkoku_ritsu_1`|
|source定義|勝率、4桁、0756→7.56|全国勝率、4桁、0580→5.80|
|identity|`toroku_bango` + `kaisai_nen` + `ki`|race自然キー + `teiban` + `toroku_bango`|
|2017+ coverage|32,183選手期レコード、2017–2026各2期|3,252,960艇、2017-01-01〜2026-09-19、24場、3,549日|
|空欄/型不正|ritsu_1の空欄・非数値なし|全国成績3列の空欄・非数値・桁数不正なし|
|原値ゼロ|`0000`が996件。欠測と決めつけず保持|`zenkoku_ritsu_1='0000'`は6,225艇。欠測と決めつけず保持|
|period|算出開始/終了年月日をsourceに保持|公式サイト出走表は開催初日の月を含む過去6か月、今節を除く|

根拠: 保存PDF p.1/p.8、xlsx「出走表(艇番)」rows18–20と
「レーサー期別成績」rows15–16。
[公式の勝率定義](https://www.boatrace.jp/owpc/pc/extra/enjoy/guide/jiten/12/y_100.html)は
着順点合計÷出走回数であり、1着率ではない。
[公式出走表の算出期間](https://www.boatrace.jp/owpc/pc/extra/about.html)は期別値と異なる。
全国成績と期別成績の異値は直ちにsource矛盾ではなく、まず別指標として扱う。
L3のraw値範囲は0000〜0943（0.00〜9.43）。race単位では542,160race×6艇。
空欄率0/3,252,960=0%。ゼロ率と欠測率を混同しない。
全列を保持する既存Rawにsource record ID/hash付きで存在する。
L3 source自然キー重複・内容矛盾0は既存Phase 2.5全件証跡による確認で、
このturnで全国勝率列の全Raw/source値比較を新たに再実行したものではない。
年別集約と再現SQL: `.local/preflight/national_score_readonly.json` / `.sql`。

KIの参考period mapping（L3採用の必須条件ではない）:

- **ユーザー指定の期区分: 5〜10月＝1期、11〜4月＝2期。**
- sourceの算出期間の観測: Y年ki1はY-1年5月1日〜10月31日、
  Y年ki2はY-1年11月1日〜Y年4月30日。
  これは保存フィールドの観測であり、ユーザー指定の有効期との対応を推測していない。
- 算出期間と利用有効期間・公開日は別。年/期だけで当時の公開完了を証明しない。
- 調査中の1〜6月/7〜12月という仮対応はユーザー訂正により撤回。
  そのjoinから算出した11,207艇という欠測数は有効期coverageとして無効で、採用判断に使用しない。
  2期の年跨ぎとsource `kaisai_nen` の対応は未確定。これをL3優先採用のblockerにはしない。
- `retrieved_at`は既存RawでNULL。当時の取得履歴・訂正版履歴がなく、
  厳密なas-known-at-T復元はNOT_CONFIRMED。

Motor A: 優先入力sourceはL3に確定。race自然キー・登録番号に対応した
そのraceの`zenkoku_ritsu_1`を使う設計とする。
現在残る課題は歴史的公開時点、ゼロ値、特殊結果とmotor generation境界の扱い。
KI未対応艇・KI適用期の確定はblockerから除外する。本計算は今回の範囲外。
公式勝率には競走格による点数差がある一方、今回提示されたmotorの着順点は固定10/8/6/4/2/1。
この定義差を記録し、ユーザー指定式を勝手に変更しない。

## D. Result anomalies

詳細は [result_anomalies_preflight.md](result_anomalies_preflight.md)。
再現コード: `scripts/preflight_results.py`。

- 特殊着順34,134件、F 12,637件、L 370件を現DBで再確認。
- 転16,083 / 欠5,942 / 落4,423 / エ2,911 / 妨2,805 /
  不1,253 / 沈414 / 失250 / ＿53。
- 公式用語説明とPC-KYOTEI R3の正式コード対応を分離。Canonicalの特殊着順はUNRESOLVEDを維持。
- 数値finish重複515組 / 515race。1raceだけ公式同着と照合できたが、残りを同着と推定しない。
- 空欄R3 41,568艇 / 6,928race:
  - 6,669race / 40,014艇はR2中止コード9に対応。
  - 254race / 1,524艇はR2初期値0かつ3連単払戻組番あり。
  - 5race / 30艇はR2初期値0かつ払戻組番も空欄。
- `＿`53raceは数値finishと共存せず、全件R2の3連単払戻組番000。
  52raceは他5艇F、1raceは他艇がエ/妨/落/転/転。
  共起から正式な意味・着順・点数を作らない。
- Rating採否・同着モデル・特殊着順点は未決定。F/LのSTを数値化していない。

## E. Odds inventory

詳細は [odds_inventory_preflight.md](odds_inventory_preflight.md)。

|分類|source / period / counts / coverage / lineage|
|---|---|
|final odds（ユーザー確認済み）|PC-KYOTEI O6、2017-03-08〜2026-09-18、525,271race、24場、63,032,520組。全raceに120通り。source原定義data_kubun=3、project分類は確定オッズ。具体更新時刻・retrieved_atなし|
|5-minute odds（ユーザー確認済み）|旧br_model.kyoteibiyori_odds_5minの保全dump。全件source_shimekiri=5。6,539,640行 / 54,497race / 24場。2024-01-01〜2025-12-15、363日。全race120組、欠測odds43,848組|
|補助CSV（主datasetへ未統合）|保全4ファイル、すべて2025-12-15福岡4R。合計300行。source_shimekiri列なし、source_urlのslider=5と取得日時あり。旧smoke観測として分離|
|実timestampの証明状況|source分類とは別項目。主sourceとも当時のsnapshot timestamp/締切差分を実測した証拠は未確認|

**ユーザー訂正**: `source_shimekiri=5`が締切5分前、それ以外のオッズは確定。
この分類規則を優先採用し、従前の「主source分類未確認」は撤回。
分類根拠はuser confirmation、実時刻証拠は別項目として保持する。

O6のrace重複・payload矛盾・不正組番順序は0。
R3観測542,004raceに対する欠測は16,733race（O6開始前9,996、期間内6,737/578日）。
O6には無投票10組と欠場350,052組を含み、数値0倍と混同しない。
CSVはsmoke3/4が各30行12組、smoke5が120行30組、smoke6が120行120組。
前3ファイルの重複key余剰は18/18/90、値競合keyは6/6/30。smoke6はどちらも0。
4ファイル間の異値は30key。O6とCSVの異値は別timing/sourceなので同時点競合と断定しない。
dumpには2024-12-28〜2025-12-14の352日欠測がある。
dumpの取得時刻は2026-08-01 22:08:36+09〜2026-08-08 05:35:11+09。
source_shimekiri=5の意味はユーザー確認済み。取得時刻をrace時点のsnapshot時刻に読み替えない。
dump内の組番重複・競合は0。dumpと他source間の全件値照合は未実施として残す。

[公式サイトの注意書き](https://www.boatrace.jp/owpc/pc/extra/about.html)にある
締切時/事故反映後の用語差はsource原定義として記録する。
projectのfinal/5-minute分類はユーザーが確認した規則に従い、勝手に別分類へ戻さない。

## F. Phase 3 blocking

1. Rating: 特殊状態、全艇結果欠測、同着確認・同着の表現と学習採否。
   `RESULT_RECORDS_PRESENT`は正常成立の証拠ではない。
2. Motor A: L3 `zenkoku_ritsu_1`優先（ユーザー訂正済み）。
   歴史的公開時点、ゼロ値・特殊結果の扱い。
   固定motor generation境界と実交換日との差も未確定。
3. Motor B: Rating本体の期待値表現・比較式が未確定。今回は実装禁止。
4. Preinfo/environment: 既存sourceの日付と今日の抽出時刻だけでは
   当時の公開・利用可能時刻を証明できない。予測時点に不明な値は利用不可。
   変数の単位・定義・venue別coverageと時点証拠を確認してから特徴量化する。
5. Odds: source分類（5=5分前、それ以外=確定）はユーザー確認済み。
   実snapshot timestampの証拠、欠測期間/欠測odds、補助CSV競合は別の未解決事項。
   Canonical統合・value・backtestは今回の範囲外。

## G. Recommended next step

次回に実装・調査可能な候補:

1. **L3全国勝率の型付き入力とlineage**: `zenkoku_ritsu_1`を優先し、
   raw 4桁→Decimal/100、race/boat/registration/source recordとの対応を明示する。
   ゼロ・欠測・historical availabilityを別状態に保ち、motor寄与計算は別段階。
2. **結果状態の証拠付き分類層**: R2の中止コード、R3欠測、
   同着の個別証拠を保持する。学習採否・着順点をまだ自動決定しない。
3. **preinfo/environmentのsource調査・正規化仕様**: C2/C3/C4等の
   実在列、単位、venue別coverage、公開時点を確認し、利用可否を定義してから実装する。
4. **oddsの時点証拠調査**: ユーザー確認済み5分前sourceのprovider履歴仕様と
   snapshot時刻・締切時刻の根拠を照合する。今回inventoryにはschema変更不要。

Rating方式14系列・motor A/B・Prediction等は方式と対象レース規則の確定後。

期間方針は [analysis_periods.md](analysis_periods.md) を維持。
自然現象development 2017–2024 / holdout 2025、Rating development 2023–2024 / holdout 2025。
直前タイムは2024以前の現存データで開発し開始window未固定、holdout 2025。
2025を見た再調整後に同じ2025を独立検証と呼ばない。
2026は1月1日起点7日ごとに利用可能な過去全体から再評価する予定であり、直近7日だけの学習ではない。
営業日DにはD-1までの境界を常に優先する。

## H. Git / additional files

本preflight checkpointの対象は以下の5ファイルのみ:

- `docs/phase3_preflight_report.md`: 本報告とユーザー訂正後の方針。
- `docs/result_anomalies_preflight.md`: 記号・年・場・他艇組合せ・未解決事項。
- `docs/odds_inventory_preflight.md`: ユーザー確認済みfinal/5-minute分類と時点証拠のinventory。
- `scripts/preflight_results.py`: 結果異常のread-only再現集計。
- `scripts/preflight_odds.py`: O6と保全CSVのread-only再現集計。

必要性は調査結果を再現し、誤った期対応・timing分類を将来へ持ち越さないため。
ユーザー承認に基づき、この5ファイルだけを独立commit・通常pushする。
確定前に保存済み実測JSONと報告書の集計・表、訂正済み仕様、Python構文、
secret/credential候補と一時生成物の非混入を照合した。全件DB集計の再実行はしていない。
調査証跡・一時集計はgitignoreされた `.local/preflight/` に置く。
今回schema変更・Canonical統合は行っていない。
