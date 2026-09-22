# Odds inventory — 2017+

実測: 2026-09-22。DBはread-only、保全dump/CSVは読み取りのみ。
Canonical統合・odds予測・value・Betting・backtestは実装していない。

## 分類

|状態|確認結果|
|---|---|
|確定オッズ / FINAL_USER_CONFIRMED（依頼A）|PC-KYOTEI O6 525,271race。ユーザー指定「それ以外のオッズは確定オッズ」による分類|
|締切5分前 / FIVE_MINUTE_USER_CONFIRMED（依頼B）|保全dump54,497race、全件source_shimekiri=5。ユーザーがこのfieldの意味を確認|
|補助CSV（両主datasetへ未統合）|4本。source_shimekiri列なし、source URLのslider=5あり。旧smoke観測として別管理|

**ユーザー確認をsource分類根拠として優先**: source_shimekiri=5は締切5分前、それ以外は確定。
従前の「主sourceのfinal/5-minute分類未確認」という結論は撤回。
分類根拠（user confirmation）と実snapshot timestampの証拠は別項目にする。
[公式説明](https://www.boatrace.jp/owpc/pc/extra/about.html)での締切時/事故反映後の区別は
source由来の定義として記録し、ユーザーのproject分類を勝手に置換しない。
R2の3連単払戻は的中組番・払戻額の結果情報であり、全120組の最終オッズsourceとして数えない。

## PC-KYOTEI O6

- source: `pckyotei.public.brd_o6`、field: `odds_sanrentan`。
- PDF `C:\Users\knkzh\Documents\kyotei\PC-KYOTEIデータ仕様書.pdf` p.3: data_kubun=3は締切時、更新時刻空白は締切時。
- 実測525,271行 / 525,271 race / 24場 / 3,482日、2017-03-08〜2026-09-18。
- 全行record_id=O6, data_kubun=3, odds_koshinjikanは4個の半角空白。retrieved_at列なし。
- 全行1,080文字＝120組×9文字（組番3＋odds6）。1〜6の異なる3艇の全順列120通りと順序まで全行一致。
- race key重複0、重複raceのpayload矛盾0。
- oddsは6桁固定小数1桁。000000=無投票、******=欠場、099999=9999.9倍以上（source定義）。
- 全63,032,520組のうち通常数値62,682,458、欠場350,052、無投票10、099999と不正tokenは0。
- 000000や******をモデル用の0倍へ変換しない。
- lineage: PC-KYOTEI公式レース情報由来のO6 → 現pckyotei。Phase 2.5 Raw対象5sourceにO6は含まれず、現project Rawにはまだ採用していない。

### Coverageと欠測

分母は観測R3自然キー542,004race。O6一致525,271、欠測16,733。
欠測内訳: 2017-01-01〜03-07に9,996、O6観測範囲内578日で6,737race。
全国暦日単位ではO6最古〜最新の欠落日0。これはrace単位の欠測0や公式開催完全性を意味しない。
L2にはさらに最新2026-09-19の156raceがある。
月別・欠測日別・欠測venue別は `.local/preflight/odds_o6_csv.json`。

|year|O6 race|
|---|---:|
|2017|44,624|
|2018|54,511|
|2019|54,541|
|2020|54,883|
|2021|54,956|
|2022|55,569|
|2023|55,390|
|2024|55,369|
|2025|55,094|
|2026|40,334|

|venue|race|observed days|最古|最新|R3に対する欠測race|
|---|---:|---:|---|---|---:|
|01|21,887|1,838|20170312|20260910|709|
|02|22,005|1,837|20170309|20260918|567|
|03|20,115|1,707|20170314|20260918|1,929|
|04|20,823|1,739|20170311|20260918|525|
|05|21,658|1,807|20170308|20260918|446|
|06|23,063|1,928|20170311|20260915|625|
|07|22,301|1,862|20170308|20260918|559|
|08|23,029|1,923|20170311|20260917|587|
|09|21,572|1,807|20170310|20260917|988|
|10|21,730|1,818|20170308|20260915|770|
|11|21,291|1,779|20170308|20260918|441|
|12|21,795|1,818|20170311|20260918|477|
|13|21,455|1,792|20170311|20260918|529|
|14|20,856|1,747|20170312|20260918|804|
|15|22,275|1,867|20170309|20260918|825|
|16|22,241|1,855|20170315|20260918|619|
|17|22,621|1,889|20170402|20260918|587|
|18|22,524|1,878|20170308|20260917|564|
|19|21,260|1,776|20170308|20260917|592|
|20|22,062|1,849|20170308|20260915|1,134|
|21|22,245|1,855|20170311|20260914|639|
|22|21,827|1,821|20170308|20260918|541|
|23|21,919|1,830|20170308|20260918|653|
|24|22,717|1,898|20170312|20260918|623|

## 保全CSV

保存先: `C:\Users\knkzh\boatrace-source-preserve\legacy-raw-observations`。
`raw_file_manifest.json`の全4件について今回SHA-256再計算が一致。
各ファイルの観測は**2025-12-15 福岡22 4Rだけ**。ファイル名2024_2025から全期間coverageを推定しない。
bet_typeは3連単。oddsは小数文字列、source_urlにはslider=5。retrieved_atは2026-08-01（レースより後の取得）。
source側の過去snapshot保持仕様・実snapshot時刻・当時の締切との差は未確認。
CSVはsource_shimekiri列を持たず、主datasetへの対応を推測して統合していない。

|file prefix|rows|distinct combinations|重複key余剰|値競合key|retrieved_at (UTC)|
|---|---:|---:|---:|---:|---|
|output_smoke3|30|12|18|6|2026-08-01T12:06:43.554Z|
|output_smoke4|30|12|18|6|2026-08-01T12:07:14.452Z|
|output_smoke5|120|30|90|30|2026-08-01T12:08:12.684Z|
|output_smoke6|120|120|0|0|2026-08-01T12:08:56.534Z|

同一race/bet/combinationで4ファイル間の異値は30key。ファイルごとの観測を統合しない。
O6との共通120keyにも値差があるが、別source・別timingであり同時点source競合とは断定しない。
smoke6は120組が一意でも、それだけで時点正当性・値の正しさを証明しない。
全hash、取得時刻、source URL、比較値はJSONに保持。

## 保全dump

source: `C:\Users\knkzh\boatrace-source-preserve\boatrace_nonreproducible_source.dump`
table: 旧`postgres.br_model.kyoteibiyori_odds_5min`。live DBでは不存在。復元せず対象tableのみstream decodeする。
manifest記載と実decodeは**6,539,640行で一致**。
`pg_restore`の対象tableのみのstdoutをstream解析し、return code 0、COPY終端あり、parse error 0。
DBへrestoreしていない。全行2017+。

|項目|実測|
|---|---|
|race日範囲|2024-01-01〜2025-12-15|
|観測日数|363日|
|race数 / venue数|54,497 / 24|
|行数 / 組番|6,539,640行、全race120行かつ120 distinct valid combinations|
|bet_type|3tのみ（3連単）|
|source_shimekiri|5のみ|
|source_endpoint|https://kyoteibiyori.com/request_odds_shousai.php|
|retrieved_at最古|2026-08-01 22:08:36+09|
|retrieved_at最新|2026-08-08 05:35:11+09|
|取得時刻distinct|54,497、各時刻120行|
|欠測期間|2024-12-28〜2025-12-14、連続352日|
|odds型 / 範囲|numeric(10,1)、有効値2.1〜9999.0|
|有効odds / 欠測odds|6,495,792 / 43,848。欠測理由は全件source_nonpositive|
|重複 / 同一key値競合 / 不正組番|0 / 0 / 0|

全raceの組番集合は揃うが、43,848組はodds欠測。欠測を0倍と扱わない。
`source_nonpositive`は旧保存tableの理由ラベルであり、元response bodyを再解析して確定した意味ではない。
取得時刻は過去レースのsnapshot時刻ではない。source_shimekiri=5とresponse hashが存在しても、
providerの歴史snapshot仕様・対応する締切時刻の証拠は未確認。
ただしユーザーがsource_shimekiri=5の意味を確認したため、**source分類は締切5分前で確定**。
実測snapshot timestampはUNKNOWNのままで、source分類をUNKNOWNへ戻す理由にはしない。
観測日範囲内の暦日欠測と、未観測開催の完全性は別。2017〜2023のこのsourceは本dumpにはない。

|venue|race|venue|race|venue|race|venue|race|
|---|---:|---|---:|---|---:|---|---:|
|01|2,281|07|2,264|13|2,263|19|2,352|
|02|2,298|08|2,358|14|2,167|20|2,141|
|03|1,983|09|2,594|15|2,445|21|2,268|
|04|2,135|10|2,270|16|2,231|22|2,268|
|05|2,232|11|2,209|17|2,400|23|2,394|
|06|2,503|12|2,232|18|1,809|24|2,400|

Lineage: provider endpoint → 旧postgres.br_model table → 2026-09-19保全dump。
manifestのdump SHA-256は `c709a9ca54f1a793f0d4cdeb7d1a63a889ceeacc979deacb3793e31e102d3d56`。
source response hashは保存されているが、今回response bodyとの再照合・provider再取得はしていない。
DDLにsource_shimekiri=5 CHECK、retrieved_at、response_sha256、source_endpoint、
PK(race_id,bet_type,kumiawase)がある。source分類はユーザー確認済み、CHECKのみから実時刻を捏造しない。

同source内のkey一意性は確認したが、dumpとCSV/他sourceの全共通keyに対する値比較は未実施。
取得時刻や意味の違いを解消する前に勝手に同一snapshotへ統合しない。

## Schemaの必要性

今回のinventoryにはschema変更不要。将来採用時は少なくともsource / raw reference / bet_type / combination / raw odds、
source分類（FINAL / FIVE_MINUTE）、分類根拠（USER_CONFIRMED等）、source原状態、
snapshot_at、retrieved_at、deadline_at、timestamp evidenceを区別する。
今後未分類sourceが出た場合にはUNKNOWNを使い、今回のユーザー確認済みsourceと混同しない。
retrospective取得日時を歴史snapshot_atへコピーしない。定義・証拠が揃うまで正式backtestに入れない。

## 再現

`scripts.preflight_odds` はsource read-onlyと保全CSV hashを確認し、全O6組番を検査する。
全計測の出力: `.local/preflight/odds_o6_csv.json`。対象範囲は2017+。
dumpのstream再現コード: `.local/preflight/odds_dump_inventory.py`、実測出力: `.local/preflight/odds_dump.json`。
Python AST/JSON構文、全行数=54,497×120、venue合計、重複/parse error 0、
最新ユーザー分類（dump=5分前、O6=確定）を最終照合した。
