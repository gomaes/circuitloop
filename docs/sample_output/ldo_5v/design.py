from circuitloop.lib import Net, finish, part

vin, gnd, vout = Net("VIN"), Net("GND"), Net("VOUT")
vfused, vprot = Net("VFUSED"), Net("VPROT")

j1 = part("TERM_2P_5.08", ref="J1")  # input: 1=VIN, 2=GND
j2 = part("TERM_2P_5.08", ref="J2")  # output: 1=VOUT, 2=GND
f1 = part("PTC_RXEF020", ref="F1")  # overcurrent: 0.2 A hold covers 0.1 A / 0.8
d1 = part("1N5819", ref="D1")  # reverse polarity: series Schottky, 40 V > 12 V
u1 = part("LM2940CT-5.0", ref="U1")
c1 = part("C_CER_50V", "470n", ref="C1")
c2 = part("C_ELEC_16V", "47u", ref="C2")

vin += j1[1], f1[1]
vfused += f1[2], d1["A"]
vprot += d1["K"], u1["IN"], c1[1]
vout += u1["OUT"], c2["POS"], j2[1]
gnd += j1[2], j2[2], u1["GND"], c1[2], c2["NEG"]

finish()
