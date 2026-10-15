# Build guide — ne555_blinker

Board: **13 × 11 holes** (33.0 × 27.9 mm) of 2.54 mm perfboard with isolated pads (one spare row/column around the circuit is included).

Hole names: columns **A, B, C …** from the left and rows **1, 2, 3 …** from the top, as seen from the **component side**. On the solder side the columns run right-to-left; the solder-side drawing is already mirrored and labelled with the same hole names.

## 1. Place and solder components (low to high)

| step | ref | part | value | pins → holes | note |
|---|---|---|---|---|---|
| 1 | D1 | 1N4007 |  | A→L2, K→L6 | cathode (band / flat) = K |
| 2 | R1 | R_1/4W | 1k | 1→I6, 2→I10 |  |
| 3 | R2 | R_1/4W | 68k | 1→G10, 2→C10 |  |
| 4 | R3 | R_1/4W | 470 | 1→F5, 2→J5 |  |
| 5 | C2 | C_CER_50V | 100n | 1→J9, 2→J8 |  |
| 6 | C3 | C_CER_50V | 10n | 1→D7, 2→C7 |  |
| 7 | J2 | HDR_1x02 |  | 1→E5, 2→D5 |  |
| 8 | U1 | NE555 |  | GND→H6, TRIG→G6, OUT→F6, RESET→E6, CTRL→E9, THR→F9, DIS→G9, VCC→H9 | socket; pin 1 notch/dot; use a DIP-8 socket |
| 9 | C1 | C_ELEC_16V | 10u | POS→C9, NEG→C8 | polarised: + to POS |
| 10 | D2 | LED_RED_5MM |  | A→J6, K→J7 | cathode (band / flat) = K |
| 11 | J1 | TERM_2P_5.08 |  | 1→J2, 2→J4 |  |

Order by height: 1 = lowest: resistors and axial diodes (bend leads to the pitch, lie flat); 2 = IC sockets, ceramic capacitors, pin headers; 3 = LEDs and TO-92 parts (observe orientation); 4 = terminal blocks; 5 = tallest: TO-220 regulators

## 2. Solder-side wiring (tinned wire / solder bridges)

Each run connects the listed holes in a straight line; solder every hole along the run. Do one net at a time and tick it off.

| step | net | run (from → to) | holes |
|---|---|---|---|
| 1 | GND | C8 → C7 | 2 |
| 2 | GND | C7 → B7 | 2 |
| 3 | GND | B7 → B3 | 5 |
| 4 | GND | B3 → K3 | 10 |
| 5 | GND | K3 → K7 | 5 |
| 6 | GND | K7 → J7 | 2 |
| 7 | GND | J7 → J8 | 2 |
| 8 | GND | K4 → J4 | 2 |
| 9 | DIS | I10 → G10 | 3 |
| 10 | DIS | G10 → G9 | 2 |
| 11 | LED_A | J6 → J5 | 2 |
| 12 | N$1 | D7 → D9 | 3 |
| 13 | N$1 | D9 → E9 | 2 |
| 14 | OUT | E5 → F5 | 2 |
| 15 | OUT | F5 → F6 | 2 |
| 16 | TIM | C9 → C10 | 2 |
| 17 | TIM | C10 → F10 | 4 |
| 18 | TIM | F10 → F9 | 2 |
| 19 | TIM | F9 → F8 | 2 |
| 20 | TIM | F8 → G8 | 2 |
| 21 | TIM | G8 → G6 | 3 |
| 22 | VBAT | L2 → J2 | 3 |
| 23 | VCC | J9 → H9 | 3 |
| 24 | VCC | I9 → I6 | 4 |
| 25 | VCC | J9 → L9 | 3 |
| 26 | VCC | L9 → L6 | 4 |
| 27 | VCC | I6 → I4 | 3 |
| 28 | VCC | I4 → C4 | 7 |
| 29 | VCC | C4 → C6 | 3 |
| 30 | VCC | C6 → E6 | 3 |

## 3. Insulated jumper wires

Solder these last, on the solder side, pad to pad, with insulated wire.

| jumper | net | from | to | approx. length |
|---|---|---|---|---|
| W1 | GND | C7 | D5 | 12 mm |
| W2 | GND | D5 | H6 | 16 mm |

## 4. Checks before power-up

- Inspect every joint; look for bridges between adjacent pads of *different* nets.
- Continuity: each net below must beep end-to-end; GND must **not** beep to any supply net.

  - `DIS`: I10, G10, G9
  - `GND`: C8, J8, C7, J7, J4, D5, H6
  - `LED_A`: J6, J5
  - `N$1`: D7, E9
  - `OUT`: E5, F5, F6
  - `TIM`: C9, C10, G6, F9
  - `VBAT`: L2, J2
  - `VCC`: J9, L6, I6, E6, H9

- First power-up through a current-limited supply; check the acceptance voltages from the verification report.
