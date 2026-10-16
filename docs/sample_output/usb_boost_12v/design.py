from circuitloop.lib import Net, finish, part

# Nets
vbus, vin, gnd, vout = Net("VBUS"), Net("VIN"), Net("GND"), Net("VOUT")
sw, gate, fb, ct = Net("SW"), Net("GATE"), Net("FB"), Net("CT")
isns = Net("ISNS")

# Connectors
j1 = part("TERM_2P_5.08", ref="J1")  # USB 5 V in: 1 = VBUS, 2 = GND
j2 = part("TERM_2P_5.08", ref="J2")  # 12 V out:   1 = VOUT, 2 = GND

# Overcurrent protection (2.5 A hold, derated limit 2.0 A)
f1 = part("PTC_RXEF250", ref="F1")
# Cycle-by-cycle current limit: 0.3 V / 0.12 ohm = 2.5 A peak
r_sns = part("R_1W", "0.12", ref="R4")

# Boost power stage
l1 = part("L_POWER_3A", "100u", ref="L1")
q1 = part("IRLZ44N", ref="Q1")
d1 = part("1N5822", ref="D1")
c_in = part("C_ELEC_16V", "100u", ref="C1")
c_out = part("C_ELEC_25V_D10", "470u", ref="C2")

# Controller
u1 = part("MC34063", ref="U1")
c_dec = part("C_CER_50V", "100n", ref="C3")
c_t = part("C_CER_50V", "560p", ref="C4")
r_gate = part("R_1/4W", "470", ref="R1")   # gate pull-down
r_fb1 = part("R_1/4W", "18k", ref="R2")
r_fb2 = part("R_1/4W", "2k1", ref="R3")

# Input path
vbus += j1[1], f1[1]
vin += f1[2], c_in["POS"], r_sns[1], u1["VCC"], u1["SWC"], u1["DRC"], c_dec[1]
gnd += (j1[2], j2[2], c_in["NEG"], c_out["NEG"], c_dec[2], c_t[2],
        u1["GND"], q1["S"], r_gate[2], r_fb2[2])

# Current sense: L1 and IPK sit on the far side of R4
isns += r_sns[2], l1[1], u1["IPK"]

# Switch node
sw += l1[2], q1["D"], d1["A"]

# Gate drive: MC34063 emitter drives the MOSFET gate
gate += u1["SWE"], q1["G"], r_gate[1]

# Timing capacitor
ct += u1["CT"], c_t[1]

# Output and feedback
vout += d1["K"], c_out["POS"], j2[1], r_fb1[1]
fb += u1["FB"], r_fb1[2], r_fb2[1]

finish()
