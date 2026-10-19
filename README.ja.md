# circuitloop

**手はんだのユニバーサル基板向けに、AIが自律的に回路を設計するCLIツール。合否判定は決定的な検証で行います。**

[English README](README.md)

回路に求める動作を `spec.yaml` に書き、`cloop run` を実行すると、次の流れが人の手を介さずに最後まで進みます。

1. AIコーディングエージェント（Claude Code または OpenCode）が [SKiDL](https://github.com/devbisme/skidl) で回路を書く
2. ERC と ngspice シミュレーションで検証する
3. エージェントが保護回路を追加する
4. 故障注入を含めてもう一度検証する
5. 2.54 mm ピッチのユニバーサル基板に組むための一式（ネットリスト、回路図、両面の配置配線図、BOM、手はんだ手順書）を出力する

```
spec.yaml ─► Phase 1 最小設計 ─► Phase 2 ゲート G1〜G3 ─┐  修正ループ
               (エージェント)       (Python)           ◄─┘  (上限 max_iter)
          ─► Phase 3 レビュー + 保護回路追加 ─► Phase 4 G1〜G3 + 回帰 + 故障注入
               (エージェント)                    (Python, 修正ループ)
          ─► Phase 5 出力: ネットリスト・回路図・基板図・BOM・手順書・レポート
```

## 設計原則

1. **合否判定は LLM にさせません。** ゲートはすべて決定的な Python コードで、終了コードと構造化 JSON レポートを返します。エージェントの役割は `design.py` を書くことと、失敗レポートを読んで直すことだけです。
2. **エージェントは検証基準を変更できません。** 次のものはエージェントから読み取り専用です。実行開始時にハッシュを記録し、エージェントの各ステップの後に照合します。変更を検知したら終了コード 3 で即停止します。
   - `spec.yaml`
   - 部品 DB
   - ルール
   - チェックリスト
   - 検証コード自体
3. **ループを制御するのは Python のオーケストレーターです。** ループ制御・状態管理・ゲート実行は circuitloop が持ちます。エージェントは 1 ステップずつ呼び出され、権限は「原則すべて拒否」です。許可するのは次の 3 つだけです。
   - 全ファイルの読み取り
   - `design.py` への書き込み
   - `cloop verify` の実行
4. **ループには上限があります。** 各フェーズの試行は初回 + 最大 `max_iter` 回の修正（デフォルト 5）です。超過すると失敗レポートを出力し、終了コード 1 で終わります。登録部品では満たせないことが証明できた仕様は、その旨を報告して終了コード 4 で終わります（[仕様が部品の性能を超えている場合](#仕様が部品の性能を超えている場合)）。
5. **全イテレーションを記録します。** 各試行の次のファイルを `runs/<timestamp>/iter_NN/` に保存します。
   - プロンプト
   - エージェントの出力
   - 設計（`design.py`）
   - ネットリスト
   - SPICE デッキ
   - レポート
6. **設計の知識はモデルではなくツールに持たせます。** 設計式（トポロジ計算器）、失敗の原因分析（診断）、ステップごとの予算は決定的な Python コードです。小さなモデルでも「選んで当てはめる」だけで済むようにしています。詳しくは「[トポロジライブラリ・診断・エージェント予算](#トポロジライブラリ診断エージェント予算)」を参照してください。

## インストール（Linux）

前提は次のとおりです。

- Linux（Ubuntu 22.04/24.04 と Arch Linux に対応。Manjaro・EndeavourOS・CachyOS など Arch 系ディストリビューションも含む。その他はベストエフォート）
- `ngspice`
- エージェント CLI（`claude` か `opencode` のどちらか 1 つ以上）

Python 3.11 以上がなければ uv が用意します。

```bash
git clone https://github.com/gomaes/circuitloop.git
cd circuitloop
./install.sh               # uv がなければ導入し、uv tool install で `cloop` を PATH に入れる
sudo apt install ngspice   # install.sh が不足を報告した場合（install.sh 自身は sudo を実行しません）
cloop doctor
```

**Arch Linux** では、先に pacman で必要なパッケージを入れてください。いずれも公式リポジトリにあります。pacman で入れた `uv` は `install.sh` がそのまま使います。

```bash
sudo pacman -S --needed git ngspice uv nodejs npm
npm install -g @anthropic-ai/claude-code      # OpenCode を使う場合は npm install -g opencode-ai
git clone https://github.com/gomaes/circuitloop.git && cd circuitloop && ./install.sh
```

`cloop doctor` は `/etc/os-release` から Arch 系かどうかを判定し、不足があれば `pacman` のコマンドを表示します。

アンインストールは `./uninstall.sh` です。`--purge` を付けると `~/.config/circuitloop` も削除します。

## エージェントのアカウントと利用規約

circuitloop は認証情報を一切扱いません。**あなたの**PCに入っているエージェント CLI（`claude -p` か `opencode run`）を改変せずにそのまま呼び出し、その CLI に**あなた自身**が設定したログインや API キーで動きます。利用者はそれぞれ自分のアカウントを使ってください。

| バックエンド | 認証方法 | 可否 |
|---|---|---|
| `claude`（Claude Code） | 自分の Claude Pro / Max / Team / Enterprise でのログイン（`claude` → `/login`） | ◯ 改変していない Claude Code に自分のサブスクリプションでサインインする使い方は認められている |
| `claude`（Claude Code） | 自分の API キー（`ANTHROPIC_API_KEY`）、または Bedrock / Vertex / Foundry の認証情報 | ◯ 料金はキーの持ち主に請求される |
| `opencode` | 各プロバイダーの API キー（Anthropic Console の API キーなど） | ◯ |
| `opencode` | Claude Pro / Max のログイン | **使わないでください**。Anthropic はサードパーティのアプリで Claude.ai のサブスクリプションにログインすることを認めていません |

次の使い方はできません。

- **自分の** Pro/Max を使って、circuitloop をホスト型サービスとして提供したり、他人の代わりに実行したりすること（他人のためにサブスクリプションの認証情報を経由してリクエストを流すことに当たる）
- 自分のログイン情報、`~/.claude` の認証情報、セッショントークンを共有・同梱すること

circuitloop をサービスとして提供する場合は、Anthropic の Commercial Terms のもとで API キーかクラウドプロバイダーの認証を使ってください。また、Pro/Max の使用上限は通常の個人利用を前提にしています。`cloop run` は1回の実行でエージェントを何度も呼び出すので、自動で大量に回すなら API キーの利用をおすすめします。

詳しくは Anthropic の [Claude Code legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)、[Consumer Terms](https://www.anthropic.com/legal/consumer-terms)、[Commercial Terms](https://www.anthropic.com/legal/commercial-terms) を参照してください。この説明は法的助言ではなく、規約は変わることがあるので、最新版を確認してください。circuitloop は Anthropic とは無関係で、Anthropic の承認を受けたものでもありません。

## 使い方

1 行の依頼から始める場合は、エージェントが `spec.yaml` を書き、確認のあとパイプラインが動きます。

```bash
cloop new "USB 5V→12V 昇圧回路を設計して"      # --yes で確認なし、--no-run で仕様の作成だけ
```

依頼に書かれていない項目（電源電圧の幅、負荷、出力電圧の範囲、リップル、保護、故障条件など）は、エージェントが一般的な設計値で埋め、1 つずつ `assumptions:` に書き出します。これは実行前に表示され、最終レポートにも載ります。仕様はスキーマと決定的な妥当性チェック（`cloop spec check`）に通ったときだけ採用されます。通らなければ問題点を返して書き直させます（最大 3 回）。確認後の仕様は手書きの仕様と同じく保護され、設計エージェントは変更できません。プロジェクトは `./<仕様名>/` に作られ、依頼文は `request.md`、仕様作成のログは `spec_gen/` に残ります。最終の公差解析で、合格範囲が登録部品の公差では満たせないと証明された場合、`cloop new` は検証済みの設計が合格する最小限だけ範囲を広げ、そのことを `assumptions` に記録して実行を完了します（`--no-relax` で報告のみ）。

テンプレートや例題から始めて、仕様を自分で書くこともできます。

```bash
cloop init my_ldo --example ldo_5v     # 空のテンプレートなら: cloop init my_board
cd my_ldo
$EDITOR spec.yaml                      # 必要なら編集
cloop run                              # 無人実行: 設計 → 検証 → 高品質化 → 再検証 → 出力
cloop status
ls output/
```

`output/` に生成されるもの:

| ファイル | 内容 |
|---|---|
| `<name>.net` | KiCad ネットリスト（SKiDL が生成） |
| `schematic.svg` | ネットラベル方式の回路図 |
| `layout_component_side.svg` / `layout_solder_side.svg` / `layout.html` | 基板の部品面とはんだ面（はんだ面は左右反転済み）。HTML はマウスを載せると詳細を表示 |
| `layout.json` | 配置と配線の機械可読データ |
| `bom.csv` | 部品 DB 由来の型番・定格つき BOM |
| `build_guide.md` | 実装順、はんだ面の配線、ジャンパー一覧、導通チェック |
| `final_report.md/.json` | 全ゲートの結果、部品ストレス表、波形 PNG、**未検証項目の明示** |
| `design.py` | 最終設計の SKiDL ソース |

## 出力例

[`docs/sample_output/`](docs/sample_output/) に、同梱の 4 つの例題（`examples/`）を Claude Code で無人実行（`cloop run`）した実際の出力を置いています。

- 5V LDO 電源（逆接続保護・過電流保護つき）
- NE555 による 1Hz の LED 点滅回路
- 単電源の 10 倍オペアンプ増幅器
- USB 5V → 12V / 0.5A の昇圧コンバータ（MC34063 ＋ 外付け MOSFET）

4 例とも、故障注入を含む全ゲート（G1〜G6）に合格しています。基板図は `layout.html` をブラウザで開くと、部品やパッドにマウスを載せて詳細を確認できます。

## コマンド

| コマンド | 内容 |
|---|---|
| `cloop new "<依頼>" [--dir D] [--yes] [--no-run] [--no-relax]` | 短い依頼から `spec.yaml` を作成し（エージェント＋決定的チェック）、確認後にパイプラインを実行する。実現不能な公差範囲は最小限だけ緩和する（後述） |
| `cloop spec check [spec.yaml]` | 仕様を検査し（スキーマ＋妥当性チェック）、合うトポロジを表示する |
| `cloop init <name> [--example X]` | プロジェクトを作成する（spec.yaml, cloop.toml, parts/, rules/） |
| `cloop run [spec.yaml] [--relax]` | 全パイプラインを無人実行する。`--relax`: 実現不能な範囲を最小限だけ広げて続行する |
| `cloop run --from design\|harden\|reverify\|output [--run DIR]` | 直近の run（または指定した run）を途中フェーズから再開する |
| `cloop verify <design.py> [--spec] [--phase design\|final] [--baseline] [--quick]` | 検証ゲートだけを実行する（人が手で直した設計の確認用）。`--quick` は公称電圧だけで故障注入なしの簡易チェック（速いが正式な判定ではない） |
| `cloop topology list [--spec S]` / `show NAME` / `generate NAME --spec S -o design.py [--set k=v] [--minimal]` | トポロジライブラリ：仕様から全部品を計算し、計算式つきの完全な design.py を書き出す |
| `cloop shopping-list [PROJECT] [--boards N] [--spares 0.1]` | 最終設計に必要なものを一覧にする：部品、IC ソケット、基板サイズ、配線材の長さ（`output/shopping_list.*` にも出力） |
| `cloop status [--json]` | 直近の run の進捗と結果を表示する |
| `cloop doctor` | Python、ngspice、エージェント CLI を確認し、不足があれば導入方法を表示する |
| `cloop parts list [--kind K] [--json]` / `cloop parts add file.yaml [--user]` | 部品 DB を管理する |

共通オプション: `--agent claude|opencode`、`--max-iter N`、`--jobs N`、`--verbose`

### シミュレーションの並列実行

1回の検証に含まれるシミュレーション（各電源電圧と各故障条件）は互いに独立なので、同時に実行します。ngspice は1プロセス1スレッドで、メモリも小さい（同梱例で約 30MB）ため、並列数は `min(使える CPU 数, シミュレーションの本数, 空きメモリ / 300MB)` で決めます。使える CPU 数は、プロセスの CPU アフィニティと cgroup の CPU 制限（コンテナ）を反映した値です。`--jobs N` か `cloop.toml` の `loop.sim_jobs` で上書きできます。エージェントのループ自体は、前回のレポートを読んで直す仕組みなので順番に実行します。

終了コード:

| コード | 意味 |
|---|---|
| **0** | 成功 |
| **1** | 設計失敗（ループ上限に到達） |
| **2** | 設定・環境エラー |
| **3** | 改ざんを検知 |
| **4** | 登録部品では仕様を満たせない（`spec_infeasible.md`、`relaxation.json`） |

## 仕様ファイル（`spec.yaml`）

書き方は [`src/circuitloop/templates/spec.yaml`](src/circuitloop/templates/spec.yaml) と [`examples/`](examples/) を参照してください。主な項目は次のとおりです。

- `power_input`: ネット名と `v_min` / `v_nom` / `v_max`。合格基準はこの 3 つの電圧すべてで判定します。
- `loads` / `stimuli`: シミュレーション時に、指定したネットへ負荷や入力信号を接続します。
- `transient`: `stop`、`step`、`settle`。
  - この項目があるときは、電源投入から始めて `t ≥ settle` の定常区間ですべてを測定します。
  - ないときは DC 動作点で判定します。収束しなかった場合はエラーにします。
- `acceptance`: 合格基準。`dc_voltage`、`ripple`、`frequency`、`gain`、`input_power`、`input_current` が使えます。
- `transient.save_step` / `transient.save_window_only`: 出力を間引き、定常区間だけを保存します。スイッチング電源のように長時間のシミュレーションが必要な場合に使います（例: `examples/usb_boost_12v`）。
- `derating`: 通常動作時に、各部品の定格の何割まで使ってよいか。
- `board`: 基板サイズの上限（穴数）。
- `parts_policy`: 部品の制約（`tht_only`、`forbidden`）。
- `protection`: 保護要件。`reverse_polarity`、`overcurrent`、`overvoltage`、`esd`、`input_protection`。
- `faults`: 故障注入の条件（`reverse_polarity`、`overvoltage`）と、そのとき満たすべき数値。
  - 故障中も、全部品が絶対最大定格を超えないことを確認します。
  - `reverse_polarity` を保護要件に入れて故障条件を書かなかった場合は、標準の故障条件を自動で追加します。
- `tolerance`: 公差解析の設定。`enabled`（デフォルト true）、`method`（`worst_case` か `monte_carlo`）、`samples`、`seed`。
- `allow_incomplete_sim`: デフォルトは `false`。SPICE モデルも等価モデルもない部品があると「シミュレーション不完全（INCOMPLETE）」となり、ゲートは不合格になります。
- `assumptions`: 依頼に書かれていなかった値（`cloop new` が書き込む）。最終レポートに表示します。
- `topology`: 省略可。`{name, params}` を書くと、Phase 1 と保護追加後の設計をエージェントではなくこの計算器で生成します（エージェントは検証に落ちたときの修正にだけ呼ばれます）。

パイプラインの設定（エージェントの種類、モデル、タイムアウト、`max_iter`、レビュー役の有無）は `cloop.toml` に書きます。

## トポロジライブラリ・診断・エージェント予算

LLM の回路設計能力はモデルによって大きく違います。そこで circuitloop は、設計の知識を決定的なコードに持たせ、モデルには「選ぶ・調整する」という小さな仕事だけを任せます。

**トポロジライブラリ**（`cloop topology list --spec spec.yaml`）。各計算器は仕様から目標値を導き、教科書どおりの式で全部品を計算し、部品 DB から**ディレーティング後の**定格を満たす部品を選び、仕様が求める保護回路を加えて、計算過程をコメントに書いた完全な `design.py` を出力します。

| トポロジ | 方法 |
|---|---|
| `ldo_regulator` | 出力電圧 ± 公差が合格範囲に収まり、保護回路の電圧降下を引いた v_min でドロップアウトを満たし、(Vin_max − Vout)·I + Vin·Iq がディレーティング後の許容損失に収まるレギュレータを選ぶ。入出力コンデンサはデータシートどおり |
| `ne555_astable` | f = 1/(ln2 (Ra + 2Rb) C)。タイミング容量はフィルムコンデンサ、デューティ約 50 % になるよう Ra ≈ 7 %。LED 抵抗は (Vcc − Voh − Vf)/I で、v_max と入力電力の上限で確認 |
| `noninverting_amp` | G = 1 + Rf/Rg を E24/E96 から選ぶ。v_min での出力振幅を確認、未使用回路の処理、入力直列抵抗 |
| `mc34063_boost` | ON Semi AN920 の手順：ton/toff、CT、Ipk = 2 Iout (ratio + 1)、Rsc = 0.3 V / Ipk、L = 2 Lmin、Co は 9 Iout ton / Vripple 以上かつ Ipk·ESR ≤ Vripple/2 となる低 ESR コンデンサの並列数、帰還分圧、MOSFET ゲートのプルダウン ≤ toff / 5 Ciss |

エージェントには仕様に合う計算器が知らされ、自分で `cloop topology generate` を実行できます（出力先は自分の `design.py` に限定）。仕様に `topology: {name: ...}` を書けば、パイプラインが自分で設計を生成し、ゲートに落ちない限りエージェントは一度も呼ばれません。どの部品でも仕様を満たせない場合は、その理由（どのレギュレータがどの定格で不足するか、など）を具体的に表示します。生成した設計はあくまで出発点で、合否はいつもどおりゲートが決めます。計算器は各部品の `design:` に書かれたデータシートの代表値（Vf、ESR、Ciss、ドロップアウトなど）を使います。

**診断**。検証に落ちると、決定的な診断器がネットリストとそれらの代表値から失敗の原因となる量を計算し直します。対象は 555 の周波数、オペアンプのゲインと出力振幅、MC34063 の設定電圧・電流制限・ゲートのターンオフ時間、ESR が支配的なリップル、レギュレータの電圧余裕と損失、LED 電流、電源経路の直列電圧降下、過渡解析が止まった原因などです。原因と「どの値をいくつに変えるか」を、エージェントに渡すレポートの **Diagnosis** 節に書きます。診断は助言だけで、合否には一切影響しません。

**エージェント予算**。エージェントの 1 ステップには `agent.timeout` 秒（デフォルト 900）と、`cloop verify` の実行回数の上限 `agent.max_self_checks`（デフォルト 4）があります。ステップ内の `cloop verify` は常に簡易チェックになり、回数か時間を使い切ると実行を拒否します。回数のカウンタはエージェントの作業ディレクトリの外にあります。ステップが終わった時点の `design.py` を、パイプラインが正式に検証します。

## 検証ゲート

| ゲート | 内容 |
|---|---|
| G1 構文・生成 | `design.py` を隔離したサブプロセス（`python -I`）で実行し、解析可能な KiCad ネットリストが出力されること |
| G2 ERC | SKiDL の ERC に加え、プラグイン形式の独自ルールで検査する（下記）。Phase 3 以降は保護回路の構成も検査する |
| G3 シミュレーション | 3 つの電源電圧それぞれで ngspice を実行し、合格基準と、全部品の定格（電圧・電流・電力）× ディレーティング率を判定する。各ピンに 0 V の電流計を挿入するので、サブサーキット部品にも適用できる |
| G4 回帰 | Phase 1 の測定値と比べて、合格基準内に収まっていること（`regression.max_drift` で変化量の上限も指定可能） |
| G5 故障注入 | 電源の逆接続・過電圧のもとで、ネット電圧・入力電流・絶対最大定格を満たすこと |
| G7 公差解析 | 最終検証のみ。公差を持つ部品値とモデルパラメータ（抵抗 ±0.1 / 1 / 5%、コンデンサ ±1 / 5 / 10 / 20%、インダクタ ±10〜20%、レギュレータや基準電圧 ±1〜5%）を、合格基準ごとに最も不利な側へ振って判定する（感度に基づくワーストケース解析。余裕が最も小さい電源電圧で実行）。`tolerance.method: monte_carlo` も選べる。合格基準と部品定格をすべて満たす必要がある |
| G6 基板 | 配置配線から接続関係を union-find で抽出し直してネットリストと照合する（断線・短絡・部品の重なり・基板サイズ） |

G2 の独自ルールで検査する項目:

- 部品が DB に登録されていて、ピン配置が一致すること
- 部品の制約（`parts_policy`）を守っていること
- 未接続のピン、ピンが 1 本しかないネットがないこと
- 浮いた入力ピンがないこと
- spec が要求するネットが存在すること
- 外部と接続するネットがコネクタに出ていること
- IC の電源ピンごとにデカップリングコンデンサがあること
- LED に直列の電流制限抵抗があること
- 部品の両端が同じネットに短絡していないこと

### 仕様が部品の性能を超えている場合

両側の範囲（`min`/`max`）が、部品の公差によるワーストケースのばらつきより狭いことがあります。たとえば、±10% のコンデンサで作る RC 発振器に周波数 ±10% を求める場合です。これはどんな設計でも合格できないので、エージェントに修正を繰り返させることはしません。Phase 4 が G7 だけで不合格になったとき、決定的な解析（`feasibility.py`）が G7 の感度から「部品 DB にある同種で最も公差の小さい部品に替えた場合のばらつき」を見積もります。

| 判定 | 意味 | 動作 |
|---|---|---|
| `recenter` | ばらつきは範囲に収まるが、中心がずれている | 診断がずらす量を示し、修正ループを続ける |
| `tighter_parts` | DB にある公差の小さい部品に替えれば収まる | 診断がその部品を示し（例: `C4 C_FILM_100V ±10 % -> C_CER_C0G_1PCT ±1 %`）、修正ループを続ける |
| `infeasible` | 最も公差の小さい部品でも収まらない | **終了コード 4** で停止し、`spec_infeasible.md` を書く |

`spec_infeasible.md` には根拠の計算と、**現在の設計が合格する最小の緩和**を書きます。違反している側の限界値だけを、その設計で検証済みのワーストケース値まで（範囲中心の 0.1% 単位で外側に丸めて）動かしたものです（同じ内容を `relaxation.json` にデータとして保存）。片側だけの限界（リップル、入力電力・電流）は設計の余裕で必ず改善できるので、実現不能とは判定しません。設計エージェントも、仕様を満たせないと確信した場合（登録部品では実現できない、など）は `spec_issue.md` に書けます。これは「未検証」と明記してレポートに引用します。

- `cloop new` はこの緩和を自動で適用します（`--no-relax` で無効）。`spec.yaml` の該当する数値だけを書き換え（コメントは残す）、変更内容を `assumptions` に記録し、元のファイルを `spec_history/` に保存して、同じ設計のまま Phase 4 から続行します。緩和は範囲を広げるだけなので、Phase 1〜3 の結果はそのまま有効です。
- 手書きの仕様では `cloop run --relax` で同じことができます。終了コード 4 で止まった直前の実行の提案を適用することもできます。`--relax` なしの `cloop run` は報告だけします。
- 限界値を範囲中心の `loop.max_relax`（デフォルト 10%）より大きく動かす緩和は、自動では適用しません。1 回の実行で緩和するのは最大 `loop.relax_rounds`（2）回までです。

### 独自 ERC ルール

`<project>/rules/` に Python ファイルを置くと、ルールとして読み込まれます。`circuitloop.rules` エントリポイントとして配布することもできます。

```python
from circuitloop.rules import Finding, Severity, rule


@rule("project.max_resistance", "1 MΩ を超える抵抗は使わない")
def check(ctx):
    return [
        Finding("project.max_resistance", Severity.ERROR, f"{c.ref} が大きすぎます", refs=[c.ref])
        for c in ctx.components_of_kind("resistor")
        if (ctx.value(c) or 0) > 1e6
    ]
```

プロジェクトのルールも spec と同じくハッシュで監視するので、エージェントは追加も編集もできません。

### 部品 DB

部品 DB は次の 3 か所の YAML から読み込みます。

- 同梱の `parts/`
- `~/.config/circuitloop/parts/`
- `<project>/parts/`

同梱の DB（`cloop parts list`、約 145 部品）は、ホビー用途の一般的なスルーホール部品を揃えています。抵抗（金属皮膜 ±1% 1/8〜1/2W、精密 ±0.1%、炭素皮膜 ±5%、酸化金属皮膜 1〜3W、セメント 5W）、コンデンサ（X7R、C0G ±5% / ±1%、PET ±10% / ±5%、PP ±5% / ±1%、電解 6.3〜100V と低 ESR 16〜50V、数 mF まで）、インダクタ（アキシャル、径 8 / 10 / 12.5mm ラジアル、10A までのトロイダル）、PTC 0.1〜2.5A と 5×20mm ヒューズ、整流・ショットキー・高速ダイオード（10A まで）、ツェナー（1W、0.5W）と TVS（600W、1500W）の電圧別ファミリー、LED、ブリッジ整流器、トランジスタ（BC547/557、PN2222A/2907A、BD139/140、TIP31/32/41/42、TIP120/125）、MOSFET（2N7000、BS170、ロジックレベル・標準ゲートの N チャネル、P チャネル）、オペアンプ（LM358、LM324、TL072、NE5532、MCP6002）、コンパレータ（LM393、LM339）、555 タイマー（NE555、TLC555）、リニアレギュレータ（78xx 5〜24V、78Lxx、LM2940、LD1117 3.3/5V、LM3940、LP2950、MCP1700、LM317）、スイッチングレギュレータ（MC34063、LM2596 / LM2576 / LM2575 降圧の 3.3 / 5 / 12V 固定と可変）、コネクタです。

部品ファミリーには `sizes` を書けます。値によって変わるデータ（本体のパッケージ・フットプリント、`design:` の値、定格）で、たとえば電解コンデンサの缶サイズ・ESR・リップル電流定格を容量に応じて切り替えます。SPICE の記述では `{d:name}` でその値を差し込めます（`{d:esr}`）。`.` で始まるキーは YAML アンカー用のテンプレートで、部品ではありません。

各部品に定義する項目:

- ピン（名前と種別）
- 絶対最大定格
- デカップリング要件（必要な部品のみ）
- 基板上のパッケージ
- SPICE モデル（`primitive`、`subckt`、`equivalent`、`connector` のいずれか）

DB に登録されていない部品は ERC エラーになります。

電流定格は、ピーク値（デフォルト）、平均値（`average`。ダイオードの If(AV) など）、実効値（`rms`。インダクタやコンデンサのリップル電流、PTC の保持電流など）のいずれで判定するかを部品ごとに指定できます。電力定格は熱的な定格なので、定常区間の平均消費電力で判定します。同梱の SPICE モデルは、データシートの代表的な特性を circuitloop 独自に動作モデル化したもので、メーカー提供のモデルではありません。省略可能な `design:` には、データシートの代表値（`vf`、`esr`、`ciss`、`dropout`、`vref` など）を書きます。トポロジ計算器と診断が使うもので、合否判定には使いません。

メーカー提供のモデルを使いたい場合は、自分でダウンロードしたモデルファイルを部品 DB から参照できます。メーカーモデルは再配布を禁じるライセンスが多いため、circuitloop には同梱しません。

```yaml
IRLZ44N_VENDOR:
  # ... ピン・定格・パッケージは通常どおり ...
  spice:
    type: subckt
    line: "X{ref} {2} {1} {3} IRLZ44N"   # メーカーのサブサーキットのノード順に合わせる
    include: models/irlz44n.lib          # この YAML からの相対パス（絶対パス・~ も可）
    compat: ps                           # ngspice の互換モード（ps = PSpice, lt = LTspice, ki = KiCad）
```

参照したモデルファイルも部品 DB と同じくハッシュで監視します。ファイルがない場合は、シミュレーションが INCOMPLETE（不完全）になります。

## ユニバーサル基板の配置配線

対象は、穴ごとに独立したパッドを持つ 2.54 mm ピッチのユニバーサル基板です。

- 配置は焼きなまし法で決めます。
- 配線は A* 探索で、はんだ面のスズメッキ線として引きます。
- 空き経路がない箇所は被覆線のジャンパーでつなぎます。

ストリップボード（パターンカット）にはまだ対応していません。

[boardwright](https://github.com/naam/boardwright) も検討しましたが、次の理由で採用していません。

- 部品の座標を人が指定する方式で、自動配置がない
- DIP/IC の図形がない

## 開発

```bash
uv sync
uv run pytest -q          # 各ゲート、不良回路のテスト、モックエージェントでの E2E（LLM は呼ばない）
uv run ruff check . && uv run ruff format --check .
```

CI（GitHub Actions）では、次の 2 つの環境で lint とテストを実行します。

- Ubuntu 24.04：Python 3.11〜3.13、ngspice は apt で導入
- `archlinux:latest` コンテナ：システムの Python、ngspice は pacman で導入。`install.sh` の動作も確認

## ライセンス

MIT ライセンスです。

ただし、SKiDL は InSpice（GPL-3.0-or-later）に依存しています。

- pip/uv で circuitloop を入れると、InSpice も一緒にインストールされます。
- SKiDL は import 時に InSpice を読み込みます。
- circuitloop 自体は InSpice を直接使いません（シミュレーションは `ngspice` 実行ファイルを呼び出します）。また、InSpice を同梱・再配布もしません。
