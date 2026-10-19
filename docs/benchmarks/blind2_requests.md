# Blind benchmark 2 — requests (registered before the first run)

Fixed on 2026-10-19 before any run, after the parts-DB expansion and the infeasibility /
relaxation work (commit `4267a17`). None of these requests was used while developing circuitloop;
the six requests of the first blind benchmark are now part of the development set.

Every request is run once with `cloop new "<request>" --yes` and the default configuration
(`max_iter` 5, agent timeout 900 s, 4 self-checks, automatic relaxation on). Results are reported
as they come out; nothing is changed between runs.

| id | request |
|---|---|
| C1 | 5VのUSB電源から3.3Vを作り、ESP32（最大500mA）に給電する電源回路を設計して |
| C2 | Arduinoの5V出力ピンで12V 1AのDCモーターをオン・オフするドライバ回路を設計して |
| C3 | 9V電池で動き、マイクの約10mVp-pの音声信号を100倍に増幅する回路を設計して |
| C4 | 24Vの産業用電源から5V 1Aを作る電源回路を設計して |
| C5 | 12V鉛蓄電池の電圧が11Vを下回ったら赤LEDを点灯させる低電圧警告回路を設計して |
| C6 | 5Vで動き、圧電ブザーを鳴らす約2kHzの方形波を出す回路を設計して |

Models: all six with `haiku`. Model comparison (one run each): C4 also with `sonnet` and `opus`.

Measured per run: result and where it stopped (phase, failing gates per iteration), wall time,
agent time and verification time, agent calls / fix attempts / spec attempts / relaxations, and
tokens (input, cache write, cache read, output) and cost from the agent CLI's own usage report.
