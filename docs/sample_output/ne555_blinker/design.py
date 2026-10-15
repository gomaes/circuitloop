from circuitloop.lib import Net, finish, part

vbat, vcc, gnd = Net("VBAT"), Net("VCC"), Net("GND")
out, dis, tim, led = Net("OUT"), Net("DIS"), Net("TIM"), Net("LED_A")

j1 = part("TERM_2P_5.08", ref="J1")   # battery
j2 = part("HDR_1x02", ref="J2")       # OUT / GND signal header
d1 = part("1N4007", ref="D1")         # reverse-polarity series diode
u1 = part("NE555", ref="U1")
r1 = part("R_1/4W", "1k", ref="R1")
r2 = part("R_1/4W", "68k", ref="R2")
ct = part("C_ELEC_16V", "10u", ref="C1")
c2 = part("C_CER_50V", "100n", ref="C2")   # VCC decoupling
c3 = part("C_CER_50V", "10n", ref="C3")    # CTRL filter
r3 = part("R_1/4W", "470", ref="R3")
d2 = part("LED_RED_5MM", ref="D2")

vbat += j1[1], d1["A"]
vcc += d1["K"], u1["VCC"], u1["RESET"], r1[1], c2[1]
gnd += j1[2], u1["GND"], c2[2], c3[2], ct["NEG"], d2["K"], j2[2]
dis += r1[2], r2[1], u1["DIS"]
tim += r2[2], u1["THR"], u1["TRIG"], ct["POS"]
u1["CTRL"] += c3[1]
out += u1["OUT"], r3[1], j2[1]
led += r3[2], d2["A"]

finish()
