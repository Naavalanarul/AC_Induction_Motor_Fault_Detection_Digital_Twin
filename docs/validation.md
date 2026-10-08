# Real-data validation and sim-to-real study

`backend/app/validation/` is an offline pipeline that:

1. tests the twin's diagnostics on **measured** motor data, and
2. puts numbers on the **sim-to-real gap**.

It never touches the live simulation. Real data is never committed. If a dataset cannot be
loaded, the CLI stops; it does not substitute synthetic data.

```bash
cd backend
pip install -r requirements-dev.txt          # includes scikit-learn + matplotlib (extra "validation")
python -m app.validation.run --dataset <name> --protocol <name> [options]
```

`--dataset` is one of `bruinsma`, `liman_c`, `estogu`, `usp_brb`, or `sim` (simulator only).

`--protocol` is one of the experiments below, or `all`. Results are written to:

```
reports/validation/<dataset>/<experiment>/
    metrics.csv   per-seed rows (all metrics, per-class recall, gaps)
    table.tex     mean ± std summary table (booktabs)
    confusion.png / few_shot_*.png / top_shifted_features_*.png
    meta.json     dataset title, version, licence, data root, verified vs assumed format,
                  split definition, seeds, model, git commit (+ dirty flag), and which of the
                  twin's four channels were evaluated
```

## 1. Datasets: download, licence, where to put them

I verified each dataset's licence and format from the publisher's metadata and the dataset
article. The exact file layout of LIMAN-C and ESTOGU, and the struct nesting of the USP files,
are not published in a form I could read. So every loader:

* lists what is **verified** and what is **assumed** (both are copied into `meta.json`);
* validates the assumptions at load time;
* stops with a message that names the fix (`--manifest`, `--column-map`, `--filename-regex`).

Unknown labels are never guessed.

| Dataset (`--dataset`) | Get it | Licence | Signals | Put files in |
|---|---|---|---|---|
| `bruinsma`: NLN-EMP, Bruinsma et al., *Data in Brief* 52 (2024) 109987 | [4TU.ResearchData](https://data.4tu.nl/datasets/2b61183e-c14f-4131-829b-cc4822c369d0): one 7z archive of CSVs, about 20.8 GB | CC0 1.0 (per the dataset's citation file) | 3 × current, 3 × voltage (after the VFD), 5 single-axis accelerometers (g), 20 kHz | `data/validation/bruinsma/` (extracted) |
| `liman_c`: LIMAN-C | [Mendeley Data kccmrf3864](https://data.mendeley.com/datasets/kccmrf3864/1) | CC BY 4.0 | 3-phase current only; 16 384 samples ≈ 4 s (≈ 4 096 Hz) | `data/validation/liman_c/` |
| `estogu`: ESTOGU | [Zenodo 18222578](https://zenodo.org/records/18222578) | **not verified**: check the record | vibration, current, voltage; With_Driver (45–50 Hz) / Without_Driver (50 Hz) | `data/validation/estogu/` |
| `usp_brb`: Treml et al., IEEE DataPort, doi 10.21227/fmnm-bn95 | [IEEE DataPort](https://ieee-dataport.org/open-access/experimental-database-detecting-and-diagnosing-rotor-broken-bar-three-phase-induction) (free login) | open access, IEEE DataPort terms | Ia–Ic, Va–Vc at 50 kHz; Vib_* at 7.6 kHz; `struct_<rs\|r1b..r4b>_R1.mat` | `data/validation/usp_brb/` |

Pass `--data-root` to use another location. Record the dataset version you downloaded; the
loader stores the folder layout it found, and `meta.json` stores the data root.

### Dataset-specific notes

**LIMAN-C**
- Every class comes from a different motor. The authors say the data must not be read as
  same-motor before/after pairs.
- The loader therefore sets `motor_group` per class. `real_only` reports that
  leave-one-motor-group-out is degenerate, and flags grouped-by-recording CV as an upper bound
  because a classifier may learn the motor rather than the fault.
- Empty CSV cells are kept as NaN; the parser keeps every row, so a missing cell never shortens
  a signal. They are then interpolated if they make up less than 1 % of the record, otherwise
  the record is skipped, and the skip is listed in `meta.json`.
- If the files are not named by condition / load / phase, pass
  `--manifest liman.csv` with columns `recording_id,condition,load_pct,phase,file`.

**Bruinsma**
- Measurement folder names encode method, motor, speed, fault and severity. The token spelling
  is parsed heuristically, and the loader stops on anything ambiguous. In that case pass
  `--manifest bruinsma.csv` with columns `folder,method,motor,speed_rpm,fault,severity`, where
  method is `vibration` or `electrical`.
- The speed in the name is the VFD **setpoint**. It is kept as metadata and is never used as a
  measured speed.
- Vibration and electrical files are separate acquisitions, so they are paired by condition and
  segment and are **not time-synchronous**.
- Accelerometer → twin axis mapping defaults to channels 1/2/3. Change it with
  `--column-map '{"vib_x":"3","vib_y":"1","vib_z":"2"}'` once you know the sensor positions.
- Loose foot, soft foot, impeller damage, cavitation, coupling degradation and bent shaft have no
  twin equivalent. They are labelled `out_of_scope` and evaluated only for healthy-vs-anomaly
  (`auroc_incl_out_of_scope`).

**ESTOGU**
- Files `{MACHINE}{LOAD}{FREQ}.csv` are parsed with a documented default pattern. Override it
  with `--filename-regex` (named groups `machine`, `load`, `freq`) or `--manifest`.
- Columns are matched by name. If that is ambiguous, pass `--column-map` with entries for
  `ia..ic`, `va..vc`, `vib_x..vib_z`, plus `"fs"` when there is no time column.
- BR (bearing ring) is mapped to the coarse class `bearing`, because inner and outer race are
  not distinguished.

**USP**
- The loader walks the `.mat` tree and takes every node with Ia/Ib/Ic. It reads the torque level
  (`torqueXX`) and the repetition from the path.
- Records whose current is noise-only (one is reported by a DataPort user for healthy torque05
  experiment 9) are flagged in metadata.
- MATLAB v7.3 files need conversion; the loader says so.

## 2. Pre-processing

| Step | What happens |
|---|---|
| Resampling | Currents/voltages → 5 kHz (twin sensor rate). Vibration → 12.8 kHz (twin accelerometer rate); USP vibration (7.6 kHz) is upsampled and therefore has no content above 3.8 kHz, which affects the 2–5 kHz bearing-envelope band. |
| Supply frequency | Estimated from the current spectrum (20–70 Hz, interpolated peak), so 50 Hz, 60 Hz and VFD operation are all handled. The simulator is run at the real data's median supply frequency, with V/f scaling. |
| Slip | No dataset has an encoder. Slip comes from one of three sources, recorded per recording in `slip_source`: <br>1. the broken-bar sideband pair f(1 ± 2s), searched with a Blackman-Harris window and accepted only if it is ≥ 12 dB above the local floor; <br>2. otherwise a load-proportional guess; <br>3. for the residual threshold study, an optional model-based fit (sensorless). <br>Simulated records go through the same estimator. They get no encoder speed either, so both domains are treated alike. |
| Framing | Vibration uses the twin's 0.5 s windows with 0.2 s hop. Current-spectrum features use 2 s windows with 1 s hop: 0.5 s cannot resolve f(1 ± 2s), and the twin's electrical diagnostic also uses 2 s. |
| Normalisation | Part of each fitted pipeline, so it is learned on the training split only. Fine-tuning keeps the simulator-fitted scaler. |
| Labels | Mapped to the twin's `DiagFault` values (`app/validation/labels.py`). Bearing faults with no stated race are mapped to the coarse class `bearing`, and evaluation happens at that granularity. Unmapped classes are `out_of_scope`. |
| Splits | Always grouped by recording (Bruinsma segments share their measurement's group), and label-stratified. Every split asserts that no group appears in two splits. |

## 3. Which twin channels can be evaluated

The CLI prints this table for every run and writes it into `meta.json` (`channels_evaluated`).

| Twin channel | bruinsma | liman_c | estogu | usp_brb |
|---|---|---|---|---|
| Electrical residual (needs current + voltage + speed) | approximate: speed from estimated slip | **not evaluable**: MCSA current-spectrum classifier instead | approximate (if voltage columns exist) | approximate |
| ML vibration/acoustic | vibration features only (no acoustic) | **not evaluable** | vibration features only | vibration features only (≤ 3.8 kHz) |
| Thermal | **not evaluable** (no temperature) | **not evaluable** | **not evaluable** | **not evaluable** |
| Supply | evaluated (false alarms) | **not evaluable** | evaluated | evaluated |

The deployed Conv-BiLSTM uses four channels, including acoustic, and none of the public sets has
acoustic. It therefore cannot be applied unchanged. The protocols instead train classifiers on
the twin's own vibration feature extractor, restricted to the axes the dataset has. They report
the Conv-BiLSTM's simulator result next to these as a reference.

## 4. Experiments

All experiments run with `--seeds 0 1 2` by default and report mean ± std. Thresholds and
hyperparameters are never chosen on a test split.

| `--protocol` | What it does | Key outputs |
|---|---|---|
| `sim_baseline` | Train/test on simulator data (grouped by run). Also includes the existing Conv-BiLSTM result from `diagnostics/ml/artifacts/metrics.json`; reproduce that with `python -m app.diagnostics.ml.train --runs-per-class 40 --seeds 0 1 2`. | accuracy, macro-F1, AUROC, ECE, Brier |
| `zero_shot` | Train on simulator data only, test on all real recordings of the common classes. | accuracy, macro-F1, per-class recall, confusion, healthy-vs-faulty AUROC, ECE, Brier, **gap = sim-test − real-test** for each metric |
| `real_only` | Leave-one-motor-group-out (folds whose classes are missing from training are skipped and listed) plus label-stratified grouped 5-fold by recording. | as above |
| `few_shot` | Pre-train an MLP on simulator data, fine-tune it on k real recordings per class (k = 1, 2, 5, 10, 20), and compare with a real-only MLP at the same k on the same held-out real recordings. | `few_shot_<view>.png`: accuracy vs k |
| `domain_shift` | Per class and per feature, sim vs real: MMD², 1-D Wasserstein, and a classifier two-sample test (grouped CV AUROC). | most-shifted features (ranked); `mcsa_sidebands.csv`: BRB f(1 ± 2s) and eccentricity f ± fr lines in dBc, real vs sim, per load bin |
| `calibration` | Fit Rs, Rr, Lls = Llr, Lm (equivalent circuit vs measured V/I phasors), rated values, sensor noise and fault-severity gains on **healthy training** recordings, then repeat zero-shot on the same real test split. | gap before/after, `gap_closure_accuracy` |
| `domain_randomisation` | Train on a randomised simulator (ranges in `simdata.py` and in `meta.json`), then repeat zero-shot. | gap and gap closure vs nominal |
| `channel_ablation` | Electrical-only (current view) vs ML-only (vibration view) vs fused, using the twin's domain weights (authoritative channel 1.0, other 0.3). Run both zero-shot and real-only. | `fusion_minus_best_single` |
| `thresholds` | False-alarm and detection rates on real data of: the MCSA BRB threshold (−45 dBc); the residual `FD_THRESHOLD` (default vs calibrated parameters × spectral vs sensorless slip); and the supply limits. Each is shown as-is and re-tuned (99th percentile of healthy **validation** windows), with rates measured on **test** windows. | false-alarm rate, detection rate |
| `severity` | Per class with ≥ 2 severity levels (bar count, Bruinsma level; healthy counts as 0), the twin's severity score per recording vs the true level. | Spearman ρ, p-value, monotonicity of per-level means |

### Remaining useful life

None of these public datasets has run-to-failure labels. RUL accuracy is therefore **not**
validated. The pipeline validates only:

* severity **ranking** (`severity`);
* the twin's prognosis on **simulated** degradation (existing test suite).

`severity/meta.json` states this.

### Quick runs and caching

| Option | Effect |
|---|---|
| `--max-records N` | Caps the number of recordings read. The cap is recorded in `meta.json`. |
| `--sim-runs-per-class` / `--sim-seconds` | Control simulator effort (defaults 20 / 4 s). |
| `--model rf\|logreg\|mlp` | Sets the window classifier. Few-shot always uses an MLP, because it can be fine-tuned. |
| `--no-cache` | Disables the feature cache. |

Feature tables are cached in `reports/validation/<dataset>/_cache/`, keyed by data root, loader
options and simulator configuration. That directory is git-ignored.

## 5. Known limitations

- **Speed.** Without an encoder, the residual channel needs a speed estimate. On simulator data, a
  slip error of about 0.009 raises healthy FD from about 0.017 to about 0.46, against a
  threshold of 0.015. The `thresholds` experiment therefore reports both the spectral and the
  sensorless (fitted) slip. The sensorless mode is optimistic, because it also absorbs part of a
  fault signature.
- **Calibration.** With current and voltage only, the steady-state impedance depends on Rr/s.
  Rr is therefore only as good as the slip estimate. With a known slip, the fit recovers Rr
  within 10 % and Lm within 5 % on simulator data (unit-tested). J cannot be identified from
  steady-state data and is scaled heuristically.
- **Untested against the real files.** Loaders were developed against the published format
  descriptions, and tested only on small stand-in files written in those formats
  (`app/tests/validation/stand_in.py`). They were not tested against the real downloads, which
  were not reachable from the development environment. Expect the first real run to need a
  `--manifest` or `--column-map`. The loaders say so explicitly; they do not guess.
