# circuitloop 技術選定と全体設計（承認待ちドラフト）

調査日: 2026-10-15。すべて実機（`--help` 実行・PyPI/npm メタデータ・実インストール）で確認した。

## 1. 依存ツール調査結果

| 対象 | 現状（確認方法） | ライセンス | 判断 |
|---|---|---|---|
| **SKiDL** | 2.3.0（2026-07）。`Part(tool=SKIDL, pins=[...])` で KiCad ライブラリなしに部品定義可能、`ERC()` と `generate_netlist()` が KiCad 未インストールでも動作することを実機確認 | MIT | **採用**。ただし下記の注意あり |
| └ InSpice（SKiDLの必須依存） | 1.7.0.7。`import skidl` 時に**必ず import される**ことを実機確認（`sys.modules` に `InSpice`） | **GPL-3.0-or-later** | ⚠ 要判断（§6 Q1） |
| **PySpice** | 1.5 が最終リリース（2021-05）。5年以上更新なし | GPL-3.0 | **不採用**。ngspice を subprocess（`ngspice -b`）で直接呼ぶ |
| **ngspice** | Ubuntu 24.04 apt で `42+ds-3build1`。`-b` バッチ＋`.control` ブロック＋`meas`/`wrdata` で数値取得できることを実機確認 | BSD系（modified BSD） | **採用**（subprocess） |
| **boardwright** | GitHub `Naam/boardwright` v0.1.0。README は `pip install` を案内するが **PyPI 未公開**。部品ピンは**絶対穴座標を人手指定**（自動配置なし）、グリフに DIP/IC なし、ストリップボードはロードマップ段階 | MIT | **不採用**（自動配置と DIP 部品が必須要件のため）。自前の配置配線を実装し、任意で boardwright 互換 JSON をエクスポートする |
| Claude Code | 2.1.300。`claude -p` に `--output-format json`, `--json-schema`, `--allowedTools`/`--disallowedTools`, `--permission-mode`, `--add-dir`, `--append-system-prompt`, `--max-budget-usd`, `--no-session-persistence`, `--bare` を確認 | — | 採用 |
| OpenCode | `opencode-ai` 1.19.0（npm, MIT）。`opencode run [message]` に `--format json`, `-m provider/model`, `--agent`, `-f`, `--dir`, `--auto`, `--pure` を確認 | MIT | 採用 |
| Typer / pydantic | 0.27.3 / 2.14.1 | MIT | 採用 |
| schemdraw | 0.23 | MIT | 回路図SVGの描画補助に検討（任意） |

## 2. 全体アーキテクチャ

```
cloop run spec.yaml
  └─ Orchestrator (Python, 状態機械)
       ├─ Phase0 spec読込 (pydantic) → 保護対象ファイルのSHA-256を記録 (spec/rules/parts DB/検証コード)
       ├─ Phase1 Agent.generate(design.py) ─┐
       ├─ Phase2 Gates G1→G2→G3 ────────────┤ 失敗→レポート(JSON+MD)→Agent.fix→再検証 (上限N)
       ├─ Phase3 Agent.harden + Reviewer(弱点列挙→修正指示のみ)
       ├─ Phase4 Gates + 回帰(Phase1基準値比較) + 故障注入
       └─ Phase5 Export (netlist/回路図/基板図/BOM/手順書/レポート)
     各イテレーション後: ハッシュ照合 → 不一致なら exit 3
```

- **合否はすべて決定的な Python**。各ゲートは `GateResult{gate, passed, findings[], metrics{}, incomplete[]}` を返し、JSON と Markdown にシリアライズ。
- **エージェントは「design.py を書く部品」**。1呼び出し＝1ステップ。ループ制御・状態（`runs/<ts>/state.json`）はオーケストレーターが保持し、`--from <phase>` はこの state から再開。

### 2.1 改ざん防止（多層）
1. エージェントの作業ディレクトリは `runs/<ts>/iter_NN/work/` のみ。spec・部品DB・ルールは**コピーを読み取り専用（chmod 0444）**で渡す。
2. Claude: `--permission-mode` + `--allowedTools "Read Write(work/**) Edit(work/**) Bash(python design.py)"` 相当で書き込み範囲を制限。OpenCode: `opencode.json` の permission で同等に制限（`--auto` は使わない方針、詳細は実装時に `--help`/公式docで再確認）。
3. **最終防衛線はハッシュ照合**。元ファイル・コピー・インストール済み検証コード（`circuitloop` パッケージ自体）のハッシュを毎イテレーション照合し、不一致で即停止（exit 3）。
4. 検証は `design.py` を**別プロセス**で実行し、出力ネットリストだけを読む（design.py が検証コードを monkeypatch できないように）。

### 2.2 エージェント抽象化
```python
class AgentBackend(Protocol):
    def run(self, task: AgentTask) -> AgentResult  # prompt, workdir, readonly_files, timeout → stdout/log/変更ファイル
```
`ClaudeBackend`（`claude -p ... --output-format json`）、`OpenCodeBackend`（`opencode run --format json --dir ...`）、`MockBackend`（テスト用：シナリオに従い固定の design.py を書く）。入出力は全て `iter_NN/agent/` に保存。

### 2.3 ゲート
- **G1**: `python design.py` をタイムアウト付き subprocess で実行 → `circuit.net`（KiCad netlist）生成を確認 → 自前 S式パーサで正規化 JSON（parts/nets/pins）へ。
- **G2**: SKiDL ERC 出力を取り込み＋独自ルール（`rules/` プラグイン、`entry_points` と ディレクトリ探索の両対応）。初期ルール: デカップリング、浮き入力/未接続、LED電流制限、ディレーティング（部品DB必須、未登録はエラー）。ディレーティングは G3 の DC 動作点結果（各素子の電圧・電流・電力）を使うため、**G2 は静的チェック、定格チェックは G3 後段に回す**（§6 Q4）。
- **G3**: 正規化ネットリスト＋部品DBの `spice:` 定義（サブサーキット or 等価モデル）から SPICE デッキを生成 → `ngspice -b` → `wrdata`/`meas` をパース → spec 合格基準と比較。モデルのない部品があれば `incomplete` に列挙し、**ゲートは合格扱いにせず「不完全」ステータス**（spec の `allow_incomplete_sim` で許可された場合のみ警告付き通過）。
- **回帰**: Phase1 合格時の主要ノード測定値を保存し、Phase4 で合格基準内かを再判定。
- **故障注入**: spec の `faults:`（例: `reverse_polarity`, `overvoltage: 15V`）ごとに入力源を差し替えたデッキを生成し、`expect:`（例: 負荷電圧 ≥ -0.3V、電流 ≤ X）を数値判定。

### 2.4 部品DB（`parts/*.yaml`）
```yaml
L78L05:
  kind: regulator_linear
  package: TO-92            # レイアウト用フットプリント（穴配置）
  pins: {1: OUT, 2: GND, 3: IN}
  ratings: {vin_max: 30, iout_max: 0.1, pd_max: 0.7}
  mpn: L78L05ACZ
  spice: {type: subckt, model: "..."}   # or {type: equivalent, ...} / なし
```
SPICE モデルは**自作の行動モデル**（555、オペアンプ、LDO）を同梱する。ベンダ提供モデルは再配布ライセンスが制限的なものが多いため同梱しない。

### 2.5 レイアウト（自前実装）
- 2.54mm グリッド、パッケージ定義（Axial 抵抗 0.4"、DIP-8、TO-92、ラジアルコンデンサ、端子台）から穴占有を計算。
- 配置: 接続度に基づく貪欲配置＋焼きなまし（基板サイズ上限は spec から、超過は決定的に失敗）。
- 配線: グリッド上の迷路ルータ（Lee/A*）。はんだ面のはんだブリッジ／スズメッキ線＋部品面ジャンパー線の2層モデル。
- 配線後に**基板から逆抽出したネットリストと設計ネットリストの一致を検証**（レイアウトもゲートとして扱う）。
- 出力: 部品面/はんだ面（左右反転）SVG、両面とホバー表示を含む HTML、ジャンパー一覧と手はんだ順序（低背→高背）の Markdown。

### 2.6 出力
KiCad ネットリスト（SKiDL 生成物）、回路図は **SVG（自前描画）**。KiCad 回路図（`.kicad_sch`）は KiCad シンボルライブラリが必要なため、`KICAD*_SYMBOL_DIR` がある環境でのみ任意生成。BOM CSV、手順書 MD、最終レポート（MD+JSON、matplotlib 波形 PNG、未検証項目一覧）。

## 3. spec.yaml（概略）
```yaml
name: ldo_5v
description: "9V入力から5V/100mAを供給するLDO電源"
power_input: {type: dc, v_min: 7.5, v_nom: 9, v_max: 12, connector: screw_terminal}
loads: [{node: VOUT, type: resistive, current: 0.1}]
acceptance:
  nodes: {VOUT: {min: 4.8, max: 5.2}}
  ripple_max: {VOUT: 0.05}
  power_max: 1.5
  derating: {voltage: 0.8, power: 0.5, current: 0.8}
analyses: [{type: op}, {type: tran, stop: 10m, step: 10u}]
board: {max_cols: 30, max_rows: 20, type: perfboard}
parts_policy: {tht_only: true}
protection: [reverse_polarity, overcurrent]
faults:
  - {name: reverse, kind: reverse_polarity, expect: {VOUT: {min: -0.3}}}
limits: {max_iter: 5}
```

## 4. CLI / 終了コード
要件どおり（`init/run/verify/status/doctor/parts add|list`、`--agent/--max-iter/--verbose`、0/1/2/3）。Typer の引数エラーも 2 に揃う。

## 5. マイルストーン（承認後）
1. spec・CLI骨格・doctor
2. 部品DB・G1〜G3（不良回路で不合格になるテスト込み）
3. オーケストレーター・エージェント抽象化（Mock で E2E）
4. 高品質化・回帰・故障注入
5. レイアウト・出力
6. install.sh / uninstall.sh / README(en/ja) / GitHub Actions

## 6. 決定事項（承認済み）
- Q1: SKiDL を採用し、InSpice（GPL）依存は README に明記する。
- Q2: 初版はパーフボード（独立パッド）のみ。ストリップボードは後日。
- Q3: このセッションで実エージェント（Claude Code）による受け入れテストを実施（3例とも完走）。
- Q4: 定格ディレーティング判定はシミュレーション結果を用いて G3 で行う。G2 は静的検査。
- Q5: SPICE/等価モデルがない部品を含む場合は INCOMPLETE として不合格（`allow_incomplete_sim: true` のときのみ警告付き通過）。

## 7. 実装中に確定した仕様
- 修正ループ: 各フェーズ「初回 + 最大 max_iter 回の修正」。
- 過渡解析がある spec では、全シナリオ（故障注入を含む）を電源投入（`uic`）から実行し、`t ≥ settle` の定常区間で測定・定格判定する。ない場合は DC 動作点を使い、収束しなければエラー（ngspice の "Transient op" フォールバックは無効な動作点として扱う）。
- 電力定格は熱的定格として定常区間の平均消費電力で判定する（当初は瞬時ピークだったが変更）。
- G6 として基板の接続を union-find で再抽出し、ネットリストと照合する。
- 外部接続ネット（電源・負荷・信号）はコネクタに出すことを ERC で要求する。
- G7 公差解析（感度ベースのワーストケース EVA または Monte Carlo）を最終検証に含める。
- モデル性能への依存を減らすため、設計知識をツール側に置く:
  - トポロジライブラリ（`src/circuitloop/topologies/`）: 仕様から目標値を導き、教科書の設計式で全部品を計算して design.py を生成する。部品はディレーティング後の定格で DB から選ぶ。生成物は出発点であり、合否はゲートが決める。spec の `topology` を指定すると、エージェントを呼ばずに設計を生成する。
  - 決定的診断（`src/circuitloop/diagnose.py`）: 失敗時にネットリストと部品の `design:`（データシート代表値）から原因量を再計算し、具体的な修正値をレポートの Diagnosis 節に書く。合否には影響しない。
  - エージェント予算: 1 ステップあたりの時間（`agent.timeout`）と `cloop verify` 回数（`agent.max_self_checks`）。カウンタは作業ディレクトリ外に置き、ステップ内の verify は常に quick。
