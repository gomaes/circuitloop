"""Reference design: MC34063 boost controller driving an external logic-level MOSFET.

Vout = 1.25 V * (1 + 13k / 1.5k) = 12.08 V. Current limit 0.3 V / 0.1 Ohm = 3 A peak.
"""

from circuitloop.lib import Net, finish, part

vbus, vin, gnd, vout = Net("VBUS"), Net("VIN"), Net("GND"), Net("VOUT")
ipk, sw, drv, gate, ct, fb = Net("IPK"), Net("SW"), Net("DRV"), Net("GATE"), Net("CT"), Net("FB")

j1 = part("TERM_2P_5.08", ref="J1")  # USB 5 V in
j2 = part("TERM_2P_5.08", ref="J2")  # 12 V out
f1 = part("PTC_RXEF250", ref="F1")  # USB overcurrent
c1 = part("C_ELEC_25V_D10", "220u", ref="C1")  # input bulk
c2 = part("C_CER_50V", "100n", ref="C2")  # MC34063 VCC decoupling
rsc = part("R_1W", "0.1", ref="R1")  # current sense
l1 = part("L_POWER_3A", "47u", ref="L1")
q1 = part("IRLZ44N", ref="Q1")
rg = part("R_1/4W", "10", ref="R2")  # gate resistor
rpd = part("R_1/4W", "220", ref="R3")  # gate pull-down (turn-off path)
u1 = part("MC34063", ref="U1")
c3 = part("C_CER_50V", "470p", ref="C3")  # timing capacitor
d1 = part("1N5822", ref="D1")
c4 = part("C_ELEC_25V_D10", "470u", ref="C4")  # output
c5 = part("C_CER_50V", "100n", ref="C5")
r4 = part("R_1/4W", "13k", ref="R4")  # feedback divider
r5 = part("R_1/4W", "1.5k", ref="R5")

vbus += j1[1], f1[1]
vin += f1[2], c1["POS"], c2[1], rsc[1], u1["VCC"], u1["SWC"], u1["DRC"]
ipk += rsc[2], u1["IPK"], l1[1]
sw += l1[2], q1["D"], d1["A"]
drv += u1["SWE"], rg[1]
gate += rg[2], q1["G"], rpd[1]
ct += u1["CT"], c3[1]
vout += d1["K"], c4["POS"], c5[1], r4[1], j2[1]
fb += r4[2], r5[1], u1["FB"]
gnd += j1[2], j2[2], c1["NEG"], c2[2], q1["S"], rpd[2], u1["GND"], c3[2], c4["NEG"], c5[2], r5[2]

finish()
