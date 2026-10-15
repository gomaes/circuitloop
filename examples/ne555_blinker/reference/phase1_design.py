"""Reference minimal design (Phase 1): NE555 astable, f = 1.44 / ((Ra + 2 Rb) C) ~ 0.99 Hz."""

from circuitloop.lib import Net, finish, part

vbat, gnd, out = Net("VBAT"), Net("GND"), Net("OUT")
dis, thr, led_a, ctrl = Net("DIS"), Net("THR"), Net("LED_A"), Net("CTRL")

j1 = part("HDR_1x02", ref="J1")  # battery snap
u1 = part("NE555", ref="U1")
ra = part("R_1/4W", "10k", ref="R1")
rb = part("R_1/4W", "68k", ref="R2")
ct = part("C_ELEC_16V", "10u", ref="C1")
cc = part("C_CER_50V", "10n", ref="C2")  # CTRL filter
cd = part("C_CER_50V", "100n", ref="C3")  # VCC decoupling
rl = part("R_1/4W", "470", ref="R3")
d1 = part("LED_RED_5MM", ref="D1")

vbat += j1[1], u1["VCC"], u1["RESET"], ra[1], cd[1]
gnd += j1[2], u1["GND"], ct["NEG"], cc[2], cd[2], d1["K"]
dis += ra[2], rb[1], u1["DIS"]
thr += rb[2], ct["POS"], u1["THR"], u1["TRIG"]
ctrl += u1["CTRL"], cc[1]
out += u1["OUT"], rl[1]
led_a += rl[2], d1["A"]

finish()
