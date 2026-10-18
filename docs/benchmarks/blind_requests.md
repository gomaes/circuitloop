# Blind benchmark requests (registered before the first run)

Fixed on 2026-10-18 before any run. None of these was used while developing circuitloop, its
prompts, topology calculators or parts. Every request is run once with
`cloop new "<request>" --yes` and the default configuration (`max_iter` 5, agent timeout 900 s,
4 self-checks). Results are reported as they come out — no prompt, part or calculator is changed
in between; anything changed after seeing a result moves that request to the development set.

| id | request |
|---|---|
| B1 | リチウムイオン電池(3.7V)から5V 1Aを出す昇圧回路を設計して |
| B2 | 12Vから3.3V 300mAを作る電源回路を設計して |
| B3 | 1kHzの正弦波発振器を設計して |
| B4 | LM35温度センサーの出力を5倍に増幅してArduinoのADCに入れる回路を設計して |
| B5 | 9V電池で動き、2つのLEDを約2Hzで交互に点滅させる回路を設計して |
| B6 | 車の12Vバッテリーから5V 2AのUSB充電出力を作る回路を設計して |
