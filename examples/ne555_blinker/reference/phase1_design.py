"""Reference minimal design (Phase 1): NE555 astable, f = 1.44 / ((Ra + 2 Rb) C) = 1.44 / (1.46 M * 1 uF) ~ 0.99 Hz."""

from circuitloop.lib import Net, finish, part

vbat, gnd, out = Net("VBAT"), Net("GND"), Net("OUT")
dis, thr, led_a, ctrl = Net("DIS"), Net("THR"), Net("LED_A"), Net("CTRL")

j1 = part("HDR_1x02", ref="J1")  # battery snap
u1 = part("NE555", ref="U1")
ra = part("R_1/4W", "100k", ref="R1")
rb = part("R_1/4W", "680k", ref="R2")
ct = part("C_FILM_100V", "1u", ref="C1")  # film: +/-10 %, unlike +/-20 % electrolytics
cc = part("C_CER_50V", "10n", ref="C2")  # CTRL filter
cd = part("C_CER_50V", "100n", ref="C3")  # VCC decoupling
rl = part("R_1/4W", "470", ref="R3")
d1 = part("LED_RED_5MM", ref="D1")

vbat += j1[1], u1["VCC"], u1["RESET"], ra[1], cd[1]
gnd += j1[2], u1["GND"], ct[2], cc[2], cd[2], d1["K"]
dis += ra[2], rb[1], u1["DIS"]
thr += rb[2], ct[1], u1["THR"], u1["TRIG"]
ctrl += u1["CTRL"], cc[1]
out += u1["OUT"], rl[1]
led_a += rl[2], d1["A"]

finish()
