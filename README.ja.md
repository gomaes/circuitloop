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
4. **ループには上限があります。** 各フェーズの試行は初回 + 最大 `max_iter` 回の修正（デフォルト 5）です。超過すると失敗レポートを出力し、終了コード 1 で終わります。
5. **全イテレーションを記録します。** 各試行の次のファイルを `runs/<timestamp>/iter_NN/` に保存します。
   - プロンプト
   - エージェントの出力
   - 設計（`design.py`）
   - ネットリスト
   - SPICE デッキ
   - レポート

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
| `cloop init <name> [--example X]` | プロジェクトを作成する（spec.yaml, cloop.toml, parts/, rules/） |
| `cloop run [spec.yaml]` | 全パイプラインを無人実行する |
| `cloop run --from design\|harden\|reverify\|output [--run DIR]` | 直近の run（または指定した run）を途中フェーズから再開する |
| `cloop verify <design.py> [--spec] [--phase design\|final] [--baseline]` | 検証ゲートだけを実行する（人が手で直した設計の確認用） |
| `cloop status [--json]` | 直近の run の進捗と結果を表示する |
| `cloop doctor` | Python、ngspice、エージェント CLI を確認し、不足があれば導入方法を表示する |
| `cloop parts list [--kind K] [--json]` / `cloop parts add file.yaml [--user]` | 部品 DB を管理する |

共通オプション: `--agent claude|opencode`、`--max-iter N`、`--verbose`

終了コード:

| コード | 意味 |
|---|---|
| **0** | 成功 |
| **1** | 設計失敗（ループ上限に到達） |
| **2** | 設定・環境エラー |
| **3** | 改ざんを検知 |

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
- `allow_incomplete_sim`: デフォルトは `false`。SPICE モデルも等価モデルもない部品があると「シミュレーション不完全（INCOMPLETE）」となり、ゲートは不合格になります。

パイプラインの設定（エージェントの種類、モデル、タイムアウト、`max_iter`、レビュー役の有無）は `cloop.toml` に書きます。

## 検証ゲート

| ゲート | 内容 |
|---|---|
| G1 構文・生成 | `design.py` を隔離したサブプロセス（`python -I`）で実行し、解析可能な KiCad ネットリストが出力されること |
| G2 ERC | SKiDL の ERC に加え、プラグイン形式の独自ルールで検査する（下記）。Phase 3 以降は保護回路の構成も検査する |
| G3 シミュレーション | 3 つの電源電圧それぞれで ngspice を実行し、合格基準と、全部品の定格（電圧・電流・電力）× ディレーティング率を判定する。各ピンに 0 V の電流計を挿入するので、サブサーキット部品にも適用できる |
| G4 回帰 | Phase 1 の測定値と比べて、合格基準内に収まっていること（`regression.max_drift` で変化量の上限も指定可能） |
| G5 故障注入 | 電源の逆接続・過電圧のもとで、ネット電圧・入力電流・絶対最大定格を満たすこと |
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

各部品に定義する項目:

- ピン（名前と種別）
- 絶対最大定格
- デカップリング要件（必要な部品のみ）
- 基板上のパッケージ
- SPICE モデル（`primitive`、`subckt`、`equivalent`、`connector` のいずれか）

DB に登録されていない部品は ERC エラーになります。

電流定格は、ピーク値（デフォルト）、平均値（`average`。ダイオードの If(AV) など）、実効値（`rms`。インダクタやコンデンサのリップル電流、PTC の保持電流など）のいずれで判定するかを部品ごとに指定できます。電力定格は熱的な定格なので、定常区間の平均消費電力で判定します。同梱の SPICE モデルは、データシートの代表的な特性を circuitloop 独自に動作モデル化したもので、メーカー提供のモデルではありません。

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
