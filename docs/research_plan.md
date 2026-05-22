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

The method will be compared against nearest-station, minimum-waiting-time, ACA,
ACA with waiting-time constraints, FIFO, no-PV-forecast, no-security, and
centralized baselines.

Metrics include rejection rate, waiting time, deadline satisfaction, grid-energy
usage, solar utilization, fairness, stale-information impact, and attack impact.

