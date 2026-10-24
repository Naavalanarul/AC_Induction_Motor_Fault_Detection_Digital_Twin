# Paper Blockers and Human Decision Log

This document tracks blocking dependencies, missing datasets, and human design decisions required for the paper evidence package.

---

## 1. Missing Datasets (Human Step: P1-1)

- **Status:** Pending user placement of dataset files.
- **Action Required:**
  Download at least one of the 4 benchmark datasets documented in `reports/paper/DATA_ACQUISITION.md` and place extracted files under `data/<dataset_name>/`:
  1. `data/liman_c/` (Mendeley Data kccmrf3864)
  2. `data/bruinsma/` (4TU.ResearchData NLN-EMP)
  3. `data/estogu/` (Zenodo 18222578)
  4. `data/usp_brb/` (IEEE DataPort doi:10.21227/fmnm-bn95)
- **Current Mitigation:**
  Following the implementation plan, while awaiting real dataset files, all non-data tasks (P2 through P8) proceed using simulator and synthetic validation splits. As soon as a real dataset is placed under `data/`, P1-2 through P1-4 can be executed immediately.

---

## 2. Key Human / Faculty Decisions

1. **Main Contribution Framing:**
   - Suggested: Hybrid multi-sensor fusion (electrical residual + MCSA + protection + ML) as the primary contribution, with SADA supervisor as a practical control contribution and sim-to-real gap analysis as the empirical evaluation.
2. **Supervisory & MHI Tuning:**
   - Approval of SADA hysteresis/dwell thresholds and confirmation of whether MHI double-counting of SADA state penalties should be retained or revised.
3. **Motor Physical Nameplate Data:**
   - Literature parameters are currently used. If physical motor test bench parameters become available, they can replace the literature default.
4. **Target Publication Venue:**
   - Venue sets the final length, layout, and balance of real vs. simulation data.
