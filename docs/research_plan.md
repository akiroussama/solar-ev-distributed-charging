# Public Research Plan

## Thesis

Design a distributed, resilient, and security-aware charging coordination system
for solar-powered EV charging stations with local battery storage.

## Core Contributions

1. `V-ASSIST`: vehicle-side station selection under range, waiting-time,
   information-age, and trust constraints.
2. `S-ACA-PD-EDF`: station-side admission control with active declassification
   from rapid to normal to slow charging and adjusted EDF queue scheduling.
3. `R-DCC`: resilient distributed coordination using signed station status
   broadcasts, temporary reservations, and stale-information penalties.
4. `TRUST-EV`: simulation-ready trust checks for replay, identity, request
   plausibility, and reservation abuse.

## Validation Strategy

The method is compared against nearest-station, minimum-waiting-time,
ACA-PD-FIFO, deadline-safe admission and feature-removal ablations:
no declassification, no EDF, no age-of-information penalty, no trust filtering,
no partial admission and no redirection.

Metrics include rejection rate, waiting time, deadline satisfaction, grid-energy
usage, solar utilization, fairness, stale-information impact, and attack impact.

The scenario matrix covers nominal operation, high demand, low irradiance,
degraded communication, explicit adversarial traffic, reduced BESS capacity,
high communication noise and no-grid autonomous operation. Each experiment cell
is repeated over deterministic random seeds and reported with means, sample
standard deviations and 95% confidence intervals.
