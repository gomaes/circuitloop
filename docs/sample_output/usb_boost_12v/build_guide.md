# Build guide — usb_boost_12v

Board: **17 × 15 holes** (43.2 × 38.1 mm) of 2.54 mm perfboard with isolated pads (one spare row/column around the circuit is included).

Hole names: columns **A, B, C …** from the left and rows **1, 2, 3 …** from the top, as seen from the **component side**. On the solder side the columns run right-to-left; the solder-side drawing is already mirrored and labelled with the same hole names.

## 1. Place and solder components (low to high)

| step | ref | part | value | pins → holes | note |
|---|---|---|---|---|---|
| 1 | D1 | 1N5822 |  | A→E7, K→K7 | cathode (band / flat) = K |
| 2 | R1 | R_1/4W | 470 | 1→K9, 2→O9 |  |
| 3 | R2 | R_1/4W | 18k | 1→G8, 2→G12 |  |
| 4 | R3 | R_1/4W | 2k1 | 1→H13, 2→H9 |  |
| 5 | R4 | R_1W | 0.12 | 1→M14, 2→G14 |  |
| 6 | C3 | C_CER_50V | 100n | 1→N12, 2→O12 |  |
| 7 | C4 | C_CER_50V | 560p | 1→J9, 2→J8 |  |
| 8 | F1 | PTC_RXEF250 |  | 1→M13, 2→O13 |  |
| 9 | U1 | MC34063 |  | SWC→L10, SWE→K10, CT→J10, GND→I10, FB→I13, VCC→J13, IPK→K13, DRC→L13 | socket; pin 1 notch/dot; use a DIP-8 socket |
| 10 | C1 | C_ELEC_16V | 100u | POS→O7, NEG→O6 | polarised: + to POS |
| 11 | C2 | C_ELEC_25V_D10 | 470u | POS→H3, NEG→H5 | polarised: + to POS |
| 12 | J1 | TERM_2P_5.08 |  | 1→M11, 2→O11 |  |
| 13 | J2 | TERM_2P_5.08 |  | 1→K5, 2→M5 |  |
| 14 | L1 | L_POWER_3A | 100u | 1→D12, 2→D10 |  |
| 15 | Q1 | IRLZ44N |  | G→L6, D→L7, S→L8 |  |

Order by height: 1 = lowest: resistors and axial diodes (bend leads to the pitch, lie flat); 2 = IC sockets, ceramic capacitors, pin headers; 3 = LEDs and TO-92 parts (observe orientation); 4 = terminal blocks; 5 = tallest: TO-220 regulators

## 2. Solder-side wiring (tinned wire / solder bridges)

Each run connects the listed holes in a straight line; solder every hole along the run. Do one net at a time and tick it off.

| step | net | run (from → to) | holes |
|---|---|---|---|
| 1 | GND | O6 → O5 | 2 |
| 2 | GND | O5 → M5 | 3 |
| 3 | GND | O6 → P6 | 2 |
| 4 | GND | P6 → P9 | 4 |
| 5 | GND | P9 → O9 | 2 |
| 6 | GND | O9 → O11 | 3 |
| 7 | GND | O11 → O12 | 2 |
| 8 | GND | M5 → M2 | 4 |
| 9 | GND | M2 → F2 | 8 |
| 10 | GND | F2 → F9 | 8 |
| 11 | GND | F9 → I9 | 4 |
| 12 | GND | I9 → I8 | 2 |
| 13 | GND | I8 → L8 | 4 |
| 14 | GND | I9 → I10 | 2 |
| 15 | GND | F5 → H5 | 3 |
| 16 | CT | J9 → J10 | 2 |
| 17 | FB | G12 → G13 | 2 |
| 18 | FB | G13 → H13 | 2 |
| 19 | FB | H13 → I13 | 2 |
| 20 | GATE | L6 → M6 | 2 |
| 21 | GATE | M6 → M9 | 4 |
| 22 | GATE | M9 → K9 | 3 |
| 23 | GATE | K9 → K10 | 2 |
| 24 | ISNS | D12 → D14 | 3 |
| 25 | ISNS | D14 → G14 | 4 |
| 26 | ISNS | G14 → K14 | 5 |
| 27 | ISNS | K14 → K13 | 2 |
| 28 | SW | E7 → E10 | 4 |
| 29 | SW | E10 → D10 | 2 |
| 30 | VBUS | M13 → M11 | 3 |
| 31 | VIN | O7 → N7 | 2 |
| 32 | VIN | N7 → N12 | 6 |
| 33 | VIN | N12 → N13 | 2 |
| 34 | VIN | N13 → O13 | 2 |
| 35 | VIN | N10 → L10 | 3 |
| 36 | VIN | N13 → N14 | 2 |
| 37 | VIN | N14 → M14 | 2 |
| 38 | VIN | M14 → L14 | 2 |
| 39 | VIN | L14 → L13 | 2 |
| 40 | VIN | L13 → L12 | 2 |
| 41 | VIN | L12 → J12 | 3 |
| 42 | VIN | J12 → J13 | 2 |
| 43 | VOUT | H3 → K3 | 4 |
| 44 | VOUT | K3 → K5 | 3 |
| 45 | VOUT | K5 → K7 | 3 |
| 46 | VOUT | K7 → G7 | 5 |
| 47 | VOUT | G7 → G8 | 2 |

## 3. Insulated jumper wires

Solder these last, on the solder side, pad to pad, with insulated wire.

| jumper | net | from | to | approx. length |
|---|---|---|---|---|
| W1 | SW | E7 | L7 | 24 mm |

## 4. Checks before power-up

- Inspect every joint; look for bridges between adjacent pads of *different* nets.
- Continuity: each net below must beep end-to-end; GND must **not** beep to any supply net.

  - `CT`: J9, J10
  - `FB`: G12, H13, I13
  - `GATE`: L6, K9, K10
  - `GND`: O6, H5, O12, J8, O11, M5, L8, O9, H9, I10
  - `ISNS`: D12, G14, K13
  - `SW`: E7, D10, L7
  - `VBUS`: M13, M11
  - `VIN`: O7, N12, O13, M14, L10, J13, L13
  - `VOUT`: H3, K7, K5, G8

- First power-up through a current-limited supply; check the acceptance voltages from the verification report.
