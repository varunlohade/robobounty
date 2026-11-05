# Scenario gaps: physics the world needs

For steve, to pass to the sim worker. These factors have no physics in `policy/highrise/` today, so `scenarios.py` lists them as not tested.

To pick up a factor, add a field to `FIELDS` in `world.py`, read it in `sim.py`, and use one of the name stems below. `scenarios.py` needs no change. A group then counts as testing the factor only when that group moves the field.

`sim.py` holds `AIR_DENSITY` as a constant today. Temperature and humidity both need it to become a value per world.

## Sand and dust (name stem: `dust`, `sand`)

| Effect | Model | Label |
|---|---|---|
| Seal leak | `A_leak = seal_leak + k_s * dust_gm2`, added to the existing leak sum | ASSUMPTION: linear, `k_s` not measured |
| Glass friction | `mu = mu_clean + (mu_dust - mu_clean) * (1 - exp(-dust_gm2 / m0))` | ASSUMPTION: form and values |
| Impeller clogging | `Q_max = Q_max0 * (1 - m_ingested / m_clog)` | ASSUMPTION: form and values |
| Sensor noise | `sigma = sigma0 * (1 + k_n * dust_gm2)`, and nose dropout rises with it | ASSUMPTION |
| Sand in the air | Threshold `u*t = A * sqrt(((rho_s - rho) / rho) * g * d)`, `A` about 0.082 for maintaining saltation. Below it no sand moves. | Source: Bagnold form, value as cited in [J. Coastal Research SI70](https://bioone.org/journals/Journal-of-Coastal-Research/volume-70/issue-sp1/SI70-106.1/Estimating-the-impact-threshold-for-wind-blown-sand/10.2112/SI70-106.1.full). `A` varies. |

Dust load at height on a tower is the first unknown. Saltating sand stays near the ground, so high floors see mostly fine dust. That last point is an ASSUMPTION from general knowledge, and I did not check it.

## Temperature (name stem: `temperature`, `temp`, `thermal`)

| Effect | Model | Label |
|---|---|---|
| Air density | `rho = p / (287.05 * T)`, used in wind drag and the orifice flow | Source: ideal gas law, textbook |
| Suction | `suction_pa_eff = suction_pa * rho / 1.225` | Source: fan pressure scales with density, [Engineering Toolbox](https://www.engineeringtoolbox.com/amp/fan-affinity-laws-d_196.html) |
| Battery resistance | `R(T) = R25 * exp(B * (1/T - 1/298))` | ASSUMPTION: Arrhenius form has [preprint support for LiFePO4](https://www.preprints.org/manuscript/202510.1447) only, `B` not measured |
| Battery capacity | `Ah(T) = Ah25 * clamp(1 + k_c * (T - 298), 0.5, 1)` | ASSUMPTION |
| Skirt stiffness | `SKIRT_COMPLIANCE_M` and `LIP_CONFORM_M` shrink below a glass transition value | ASSUMPTION: no data found |

## Humidity and condensation (name stem: `humid`, `condens`)

| Effect | Model | Label |
|---|---|---|
| Saturation pressure | `e_s = 6.1094 * exp(17.625 * t / (t + 243.04))` hPa, `t` in deg C | Source: [Alduchov and Eskridge 1996](https://www.osti.gov/biblio/548871). I checked the citation but not these coefficients against the paper. |
| Moist air density | `rho = (p - e) / (287.05 * T) + e / (461.5 * T)` | Source: ideal gas mix, textbook |
| Condensation on glass | `wetness_eff = max(wetness, clamp((T_dew - T_glass) / dT, 0, 1))` | ASSUMPTION: ramp and `dT` |

This needs a temperature field first.

## Rain (name stem: `rain`, `precip`)

The chat "rainy coastal city" needs this. The `wetness` field covers wet glass friction only.

| Effect | Model | Label |
|---|---|---|
| Wetting | `wetness_eff = 1 - exp(-R_mm_h / R0)` | ASSUMPTION |
| Sheeting water at the seal | Extra leak or a better seal: sign unknown, so test both | ASSUMPTION |
| Nose sensor | Dropout rises with `R_mm_h` | ASSUMPTION |

## Wind by height (name stem: `profile`, `shear`)

Wind in `sim.py` does not depend on height today. `drop_below_roof_m` changes only the tether length.

| Effect | Model | Label |
|---|---|---|
| Wind at the robot | `U(z) = U_ref * (z / z_ref) ^ alpha`, with `alpha` from terrain | Source: power law, textbook. I did not confirm a citation for `alpha`, so treat its value as ASSUMPTION. |

## Also absent

Salt, ice and snow have no physics, and I propose no model for them. The sun level changes the picture only: `sim.py` and `world.py` do not read `sun_level` at all, so it is not a physics field.
