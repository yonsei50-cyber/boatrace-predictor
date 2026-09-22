# Environment / preinfo source inventory

Inventory observation started: 2026-09-22T15:08:35.562623+00:00。対象は2017-01-01以降。

## A. Verdict

**PREFLIGHT_PASS_WITH_LIMITATIONS**。C2/C3/C4の全件source inventoryと保存定義照合を完了。予測利用可能性はユーザー指定のpre-race source方針に基づき、retrieved_at欠如だけで学習除外しない。ただしC4の数値形式を一律VALIDとして採用すること、未確定の単位や数量を推定することはまだできない。

## B. Phase 3B checkpoint

- commit: `69d4f70e7d392c55ae5c07c2c69dfd97aab49025` / `feat(results): classify race and finish states`
- branch: `main`。local HEAD / origin/main / 実remote mainの一致を通常push後に確認。新しい基準HEAD。
- Phase 3Bの指定9ファイルのみcommit。force push / history rewrite / unrelated file追加なし。
- 93 tests再実行PASS。全件checkpoint auditは前回JSONと完全一致。lineage不一致0、Canonical重複0、R2 542,004件、再実行追加0の証跡、Canonical/frozen/D-1維持。
- race状態: 535,076 / 6,669 / 254 / 156 / 5。特殊記号34,134件・重複515race・未解決5raceを推測補完せず、本番F12,637/L370は数値ST化なし。
- push直後のworking treeには次段階inventory scriptだけが未追跡で残った。本inventoryのscript/reportは未commit。

## C. Environment sources

主sourceは `pckyotei.public.brd_c2`、自然キー `(kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no)`、race粒度。2017-01-01〜2026-09-18、24場、542,003race。L2の同終了日まで542,004raceに対して1race欠落（2022-04-09児島4R）。L2最新2026-09-19の156raceも含めると157race未収録。C3も同一race範囲。
以下の空欄率はC2レコード内542,003件を分母とし、レコード自体の欠落とは別。NULL/空文字は0、空白文字列を原値のまま数えた。

|対象|field|観測raw範囲|空欄|zero raw|単位・code|
|---|---|---|---|---|---|
|風速|fusoku|00〜18|6,619 (1.221%)|35623|PDF表記 m。物理単位m/sの明示対応は未確認。|
|風向|fuko_code|01〜16|42,243 (7.794%)|0|方角コード。01北〜16北北西、22.5度刻みのコード表。|
|波高|hako|00〜40|6,621 (1.222%)|42515|PDF表記 m と公式表示cmが矛盾。cm候補だが正規化単位はUNRESOLVED。|
|天候|tenki_code|1〜6|485 (0.089%)|0|1晴/2曇り/3雨/4雪/5台風/6霧。|
|気温|kion|-62〜400|6,619 (1.221%)|855|℃、3桁固定小数1桁（例250→25.0）。|
|水温|suion|-30〜380|6,619 (1.221%)|29|℃、3桁固定小数1桁（例240→24.0）。|

風速00の35,623件は全件風向空白。気象一式欠測6,619件も風向空白。さらに風速02で風向空白が1件ある。無風に伴うsource空欄と欠測候補を分けて保持し、風向0や北に補完しない。0℃・水温0・無風・波高0は値としてあり得るため、0を一括sentinelへ変換しない。負の気温/水温も原値を維持する。

`hogaku_code`も01〜16、全542,003件に存在。場の方角と風向は別fieldであり、今回相対風向やcourse作用を計算しない。`suimenkisho_joho`はHHmmの水面気象情報markerで、後述の時刻制約がある。

その他候補をread-only確認: R2は542,004件、K2は541,932件、K3は3,211,650件（各2017-01-01〜2026-09-18）。R2/K2の気象・K3の展示タイムは結果sourceに格納されているため、そのままpre-race代替へ採用しない。保存dump manifestの5tableは設定/odds/結果label/更新暦/定義で、独立したenvironment/preinfo Rawの収録は確認できなかった。旧architectureを再利用していない。

## D. Preinfo sources

C3はrace×boat_no、3,252,018艇 / 542,003race、24場、2017-01-01〜2026-09-18。全race6艇。C4もrace×boat_noで874,555艇 / 145,761race、23場、2023-10-12〜2026-09-18。145,750raceが6艇、11raceが5艇（すべて児島、2025-12〜2026-01）。各source PKとL2照合でorphan0。

|対象|source.field|raw例・尺度|非zero整数形式|空白/空文字|0000|
|---|---|---|---|---|---|
|展示|C3.tenji_time|0671→6.71秒（PDF明示）|3207528|0|44490|
|チルト|C3.tilt|-05→-0.5、space+05→0.5、space+00→0.0|非空欄3,209,860|42158|0.0は有効値|
|一周|C4.isshu|例3729。固定小数scaleの正式対応は未確認|797401|40404|36750|
|半周|C4.hanshu|例2145。半周のまま保持|40316|834151|88|
|回り足|C4.mawariashi|例0556。正式scale未確認|841760|16992|15803|
|直線|C4.chokusen|例0706。正式scale未確認|746462|112800|15293|

C3展示0000は保存PDF p.4の初期値0を4桁保持したsource初期値としてSOURCE_SENTINEL候補。0秒にしない。チルトの先頭spaceは符号位置のpaddingであり、空白行とは別。C4の0000は提供元が取得不能時の仕様と説明しているためSOURCE_SENTINELとして区別可能。ただしC4の非zero数値には誤対応等があり、上表の「整数形式」はVALID保証ではない。

C4の保存PDF/workbookには専用定義がなく、現DBcolumnと提供元manual・保存mappingでfield存在を確認した。半周→一周のfallbackは禁止し、別変数のまま扱う。古いmappingにあるfallback方針は採用しない。

### C4 quality / source変更

提供元forum（2025-08-27）には欠場艇のboat-slotずれ、前race値の持越し、中止raceへの前race値残存、0000、レコード不存在が報告されている。提供元回答に原因解明や過去修復完了の宣言はなく、historical repair statusはUNKNOWN。報告日・対象日はsourceデータの取得日を意味しない。

今回確認した原値例: 2024-03-26宮島3R艇1は isshu=0004 / mawariashi=0005 / chokusen=0006、2024-01-02児島12R艇5は isshu=0000 / mawariashi=0691 / chokusen=3833。これらを数値形式だけで正常値にしない。2026-05-29大村12R艇3のisshu=6877も診断対象として保持。閾値除外・値入替え・前後艇への再割当てはしていない。

提供元manualは2025-04-11以降、取得失敗raceを初期値で埋めず除外する変更を説明する。現DBでは同日以降にも全4fieldがblank/0000の艇5,355件、いずれか0000の艇15,642件が存在する。艇単位の欠測とrace単位の取得失敗は同じではないため、説明だけで過去行の状態を決めない。変更前後のmissing率は収録方式差を含む。

## E. Start exhibition

|項目|C3 source|coverage / 原値|本番sourceとの分離|
|---|---|---|---|
|展示進入|tenji_shinnyu_course|1〜6: 3,206,994艇 / space:45,024艇|R3.shinnyu_course / actual_courseとは別|
|展示ST|tenji_st + tenji_kigo|ST 3桁、016→0.16秒。記号はspace/F/Lを実測|R3.st/kigo / start_timingとは別|

|展示記号|ST raw状態|艇数|
|---|---|---|
|space|非zero3桁|2464955|
|space|000（0.00候補）|35405|
|space|空白|45031|
|F|非zero3桁|706121|
|F|空白|28|
|L|空白|478|

展示F合計706,149、L478。本番F12,637/L370とは異なる観測。F/Lを通常数値STへ変換しない。FでST空白28件も原記号を維持する。PDFは展示kigoのK/Sも定義するが、対象範囲の実測は0。boat_noはidentity、展示進入と本番actual_courseは別attribute。

## F. Part changes

C3の9個の専用fieldが複数同時に非zeroとなる構造。race×boat_no×part_typeへunpivotでき、1対多の表現は可能。数量や交換なしを補完せずraw codeを保持する。

|part field|raw分布|非zero艇数|
|---|---|---|
|propeller|0:3252018|0|
|piston|0:3234277, 1:2683, 2:15058|17741|
|piston_ring|0:3196883, 1:18261, 2:21633, 3:2569, 4:12672|55135|
|denki_isshiki|0:3238483, 1:13535|13535|
|carburetor|0:3235886, 1:16132|16132|
|cylinder|0:3242356, 1:9662|9662|
|crankshaft|0:3248022, 1:3996|3996|
|gearcase|0:3240095, 1:11923|11923|
|careerbody|0:3236447, 1:15571|15571|

PDF p.4は0を初期値、1を部品交換、pistonは1〜2、piston_ringは1〜4の交換コードと定義。複数値を持つ2fieldは数量表現候補だが、今回の定義文は交換コードであるため「個数」としての厳密な対応確認を残す。その他1は交換フラグとして確定できても、未確認のquantity=1は生成しない。0は初期値であり「交換なし」を全件保証しない。propeller全件0も交換が物理的になかった証明ではない。

|同時非zero part field数|艇数|
|---|---|
|0|3141013|
|1|90193|
|2|11600|
|3|7077|
|4|1710|
|5|344|
|6|58|
|7|21|
|8|2|

1種類以上111,005艇、2種類以上20,812艇。部品種類・raw value・race×boat identityは全件追跡可能。空欄/未知コードは現在0だが、将来不明値を1個と推測しない。

## G. Venue-specific structural missing

|場/条件|構造仕様|実データとの一致|
|---|---|---|
|桐生01|展示あり、一周なし、半周あり|C4 40,404艇。一周全空白、半周40,316非zero+88 sentinel|
|江戸川03|展示あり、C4の一周/半周/回り足/直線なし|C3あり、C4レコード0|
|住之江12|直線なし|C4直線34,290艇すべて空白|
|尼崎13|直線なし|C4直線39,312艇すべて空白|
|徳山18|直線なし|C4直線39,198艇すべて空白|
|桐生以外|半周を一周へ代用しない|半周834,151艇はspace/empty。field構造として区別|
|若松20|過去の回り足提供開始は未確定|16,992艇空白、非zero初観測2025-02-16。historical非提供か取得欠落か未確定|

推奨する将来の状態: VALID（形式/定義/対応を確認済み）、STRUCTURALLY_NOT_PROVIDED（場×field×必要なら期間の正式仕様）、MISSING（提供対象の空欄/行不存在）、SOURCE_SENTINEL（初期値/取得不能コード）、INVALID（確定仕様違反）、UNRESOLVED（意味/scale/対応/時期未確定）。今回これらのschemaや特徴量を実装していない。

C4のvenue別現存期間と提供中断候補を以下に示す。first/lastは観測境界であり、公式提供開始/終了の証明ではない。C3にはその後も観測があるため、常滑/住之江/丸亀/児島のC4末尾を開催終了と読み替えない。

|場|C4 first|C4 last|艇数|
|---|---|---|---|
|01 桐生|20231012|20260910|40404|
|02 戸田|20231020|20260918|40788|
|03 江戸川|なし|なし|0|
|04 平和島|20231012|20260918|37824|
|05 多摩川|20231015|20260918|40062|
|06 浜名湖|20231123|20260915|41622|
|07 蒲郡|20231012|20260918|41784|
|08 常滑|20231013|20260323|35208|
|09 津|20251023|20260917|12240|
|10 三国|20231012|20260915|40482|
|11 びわこ|20231012|20260918|38796|
|12 住之江|20231013|20260408|34290|
|13 尼崎|20231101|20260918|39312|
|14 鳴門|20231013|20260918|37692|
|15 丸亀|20231012|20260725|40650|
|16 児島|20231012|20260203|29455|
|17 宮島|20231017|20260918|42846|
|18 徳山|20231012|20260917|39198|
|19 下関|20231013|20260917|39360|
|20 若松|20231023|20260915|39606|
|21 芦屋|20231012|20260914|40830|
|22 福岡|20231012|20260918|39990|
|23 唐津|20231015|20260918|39774|
|24 大村|20231012|20260918|42342|

## H. Timing safety / lineage

**予測利用方針**: C2/C3/C4は直前情報sourceであり、ユーザー指定に従い対象race前の情報として利用候補にできる。個別retrieved_atの欠如だけを理由に2017+学習から除外しない。これはsource-class上の運用方針で、過去のexact as-of監査証明とは別。C4 manualの「最速締切12分前」は収録可能性であり、全raceの−12分取得保証ではない。決定時点が早ければ未公開の可能性がある。

**監査timestamp**: C2/C3/C4 base tableにretrieved_at/更新履歴/過去版保持はない。現在のread-only REPEATABLE READ snapshot、source locator、PK、raw値・集計・例を保存した。新RawにはC2/C3/C4がまだ存在せず、source_batch/recordへの永続lineageは未実装。Canonical化前に全原行をRaw frameworkへ保存する必要がある。

**C2 marker**: suimenkisho_johoのHHmm形式44,807件、blank497,196件（HHmmのうち0000が349件）。43,501件はL2名目締切より後。主に1Rにのみmarkerがあり、他raceは空白。例: 2026-09-18戸田1R marker1558 / 締切1047。これは個別raceの公表/取得時刻を証明しないためas-of timestampとして使わない。名目締切との比較だけで実終了後更新や全C2 leakageとも断定しない。

公式beforeinfoを今回参照した時点では同raceの気象表示が16:38現在であり、raw marker1558や天気code2とも同一snapshotではなかった。一方C3展示0665・tilt-05・展示進入1・F004は表示と対応した。現在の画面を過去Raw全件の時刻証明にしない。波高は画面cm/PDF mの矛盾を保持する。

**混入禁止**: 結果source R2/K2/K3を時刻未検証のままpre-race代替にしない。L2安定板anteiban_shiyoは0初期/1使用だが、予測時点利用可否はUNKNOWNで今回は対象外。既存D-1結果境界は変更しない。

## I. Data periods

|source|2017〜2024 development（race / boat rows）|2025 holdout|2026現存範囲|
|---|---|---|---|
|C2|445,223 race|55,908 race|40,872 race|
|C3|445,223 race / 2,671,338艇|55,908 race / 335,448艇|40,872 race / 245,232艇|
|C4|61,292 race / 367,752艇|50,196 race / 301,172艇|34,273 race / 205,631艇|

C4のdevelopmentデータは現存する2023-10-12〜2024-12-31の範囲であり、直前タイムのdevelopment開始windowを固定したものではない。津C4には2024以前がなく、若松回り足にも2024以前の非zero値がない。2025はholdoutとして維持し、収録仕様変化や品質調査からモデル/閾値を選んでいない。2026の7日ごとの再評価・学習・予測は未実施。

|time field|development 非zero整数形式|2025 非zero整数形式|注意|
|---|---|---|---|
|brd_c3.tenji_time|2634768|330667|0000除外、未補完|
|brd_c4.isshu|336560|272342|C4はVALID未保証|
|brd_c4.hanshu|16580|13356|C4はVALID未保証|
|brd_c4.mawariashi|344952|291692|C4はVALID未保証|
|brd_c4.chokusen|313961|253504|C4はVALID未保証|

### 年別source coverage

|year|L2 race|C2 race|C2 rows|C3 race|C3 boats|C4 race|C4 boats|
|---|---|---|---|---|---|---|---|
|2017|55032|55032|55032|55032|330192|0|0|
|2018|55332|55332|55332|55332|331992|0|0|
|2019|55176|55176|55176|55176|331056|0|0|
|2020|55464|55464|55464|55464|332784|0|0|
|2021|55728|55728|55728|55728|334368|0|0|
|2022|56436|56435|56435|56435|338610|0|0|
|2023|55992|55992|55992|55992|335952|10680|64080|
|2024|56064|56064|56064|56064|336384|50612|303672|
|2025|55908|55908|55908|55908|335448|50196|301172|
|2026|41028|40872|40872|40872|245232|34273|205631|

年×venue×fieldのNULL/empty/space/zero/integer/other件数、全raw値分布、非blank/非zero初終観測、part/ST明細は `.local/environment_preinfo/inventory.json`。これらraw-shapeカテゴリはsemantic statusではない（例: 正のtiltはpadding付きOTHER_TEXTでも有効形式）。

## J. Blocking / unresolved

1. C4の艇対応ずれ・前race持越し等を検出する方針、原観測revisionの扱い、affected期間の検証が必要。数字だけをVALIDとして一括Canonical化しない。
2. C4のfield別scaleの正式根拠、波高単位矛盾、風速m表記の物理単位対応を確定する。経験則だけで変換しない。
3. C2 HHmm markerのrace/venue-day意味は未解決。as-of証明には使わず、pre-race source利用方針と監査時刻を別管理する。
4. Partsの交換codeと厳密quantityの対応確認。0初期を交換なし、flag1を1個と推測しない。
5. C4開始/停止や若松回り足の歴史的非提供期間の理由はUNKNOWN。absenceとSTRUCTURALLY_NOT_PROVIDEDを混同しない。
6. C2/C3/C4の新Raw lineage追加は次段階。今回はsource DB・target DBとも永続データ/schema変更なし。

## K. Recommended implementation order

1. 全原行保持のC2/C3 Raw追加を既存frameworkで行い、natural key・record/batch hash・provenanceを確保する。
2. C3展示進入・展示ST/記号・展示タイム・tiltを別fieldでCanonical化。0.00 ST、F/L、sentinel、padding、行不存在を分離する。
3. C2の定義確定済み気温・水温・天気/方角codeをCanonical化し、風速/波高の単位を確定して追加。HHmm markerは監査情報として独立保持。
4. Partsはpart_type/raw codeを1対多で保持し、quantityは根拠のある部分だけ設定。
5. C4は先にRaw保持・field scale・過去品質・場別期間の検証を終え、その後に半周/一周/回り足/直線を分離してCanonical化する。
今回はsource inventory / feasibilityのみ。特徴量本計算、Rating、motor、F休み、進入指数、モデル、Prediction、3連単、odds/value/betting、2026 walk-forwardへ進んでいない。

### Evidence and reproducibility

- [保存PC-KYOTEI仕様書](C:/Users/knkzh/Documents/kyotei/PC-KYOTEIデータ仕様書.pdf) p.4/p.10。
- [保存テーブル定義書](C:/Users/knkzh/Documents/kyotei/PC-KYOTEIテーブル定義書.xlsx) 直前情報(レースNo) rows20–27、直前情報(艇番) rows39–41等。
- [提供元original exhibition manual](https://pc-kyotei.com/originaltenjitime/)（場別提供・取得時刻・2025-04-11変更）。
- [提供元C4不備forum](https://pc-kyotei.com/forums/topic/%E3%82%AA%E3%83%AA%E3%82%B8%E3%83%8A%E3%83%AB%E5%B1%95%E7%A4%BA%E3%82%BF%E3%82%A4%E3%83%A0brd_c4%E3%81%AE%E3%83%87%E3%83%BC%E3%82%BF%E4%B8%8D%E5%82%99%E3%81%AB%E3%81%A4%E3%81%84%E3%81%A6/)（2025-08-27報告）。
- [公式beforeinfo戸田2026-09-18 1R](https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20260918&jcd=02&rno=1)（現在参照時の表示、Rawと同一snapshotではない）。
- 保存manifest `C:\Users\knkzh\boatrace-source-preserve\SOURCE_MANIFEST.md`。旧mappingは補助資料のみで、新しいmodel/schemaとして再利用しない。
- 再現script: `scripts/preflight_environment_preinfo.py`。source接続READ ONLY、集計とraw分布の総和・SQL count・year/venue総和を照合PASS。

```powershell
& 'C:\Users\knkzh\AppData\Local\Python\bin\python.exe' -X utf8 -B -m scripts.preflight_environment_preinfo --report 'C:\Users\knkzh\Documents\boatrace-predictor\.local\environment_preinfo\inventory.json'
```
