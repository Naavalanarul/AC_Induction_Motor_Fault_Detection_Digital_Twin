"""Experiments (each writes metrics.csv, table.tex, PNGs and meta.json; see reporting.py).

    sim_baseline          1  train/test on simulator data
    zero_shot             2  train on simulator, test on real; gap = sim-test metric - real-test metric
    real_only             3  grouped CV on real data (leave-one-motor-group-out where possible)
    few_shot              4  sim pre-training + fine-tuning on k real recordings/class vs real-only
    domain_shift          5  MMD / Wasserstein / classifier two-sample test; MCSA sideband dB sim vs real
    calibration           6  fit the twin to real healthy recordings, then repeat zero-shot
    domain_randomisation  7  randomised simulator training, then repeat zero-shot
    channel_ablation      8  electrical-only vs ML-only vs fused (twin domain weights)
    thresholds            9  false-alarm rate of the twin's residual/MCSA/supply thresholds on real
                             healthy data, as-is and re-tuned on a held-out real validation split
    severity             10  Spearman correlation of the twin's severity score with true severity

Rules enforced here: splits are grouped by recording (asserted), nothing is tuned on a test split,
every result carries seeds, split definition, git commit and evaluated channels.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.validation import calibration as CAL
from app.validation import features as FT
from app.validation import metrics as M
from app.validation import models as MD
from app.validation import reporting as R
from app.validation import simdata as SD
from app.validation import splits as S
from app.validation import table as T
from app.validation import twin_channels as TC
from app.validation.labels import HEALTHY, OUT_OF_SCOPE, TWIN_LABELS
from app.validation.loaders import DatasetLoader
from app.validation.preprocessing import prepare

log = logging.getLogger(__name__)
CACHE_VERSION = "v1"


@dataclass
class Context:
    dataset: str
    out_root: Path
    seeds: list[int]
    loader: DatasetLoader | None = None
    real: T.FeatureTable | None = None
    model_kind: str = "rf"
    sim_runs_per_class: int = 20
    sim_seconds: float = 4.0
    ks: tuple[int, ...] = (1, 2, 5, 10, 20)
    test_fraction: float = 0.3
    val_fraction: float = 0.2
    cache_dir: Path | None = None
    run_meta: dict = field(default_factory=dict)
    _sim_cache: dict = field(default_factory=dict)

    # ---- shared helpers ----------------------------------------------------------------------
    @property
    def rt(self) -> T.FeatureTable:
        """The real-data table (protocols that call this have checked that it exists)."""
        if self.real is None:
            raise ValueError("this protocol needs a real dataset")
        return self.real

    @property
    def axes(self) -> tuple[str, ...]:
        return self.real.axes if self.real is not None else FT.VIB_AXES

    def views(self) -> list[str]:
        if self.real is None:
            return list(T.VIEWS)
        return [v for v in T.VIEWS if self.real.has(v)]

    def real_labels(self) -> list[str]:
        labs = sorted({r["label"] for r in self.real.records}) if self.real else []
        return [lab for lab in labs if lab in TWIN_LABELS]

    def common_classes(self) -> list[str]:
        """Classes present in the real data that the simulator can produce (OUT_OF_SCOPE excluded)."""
        return [c for c in self.real_labels() if c in SD.SIM_FAULTS]

    def supply_freq(self) -> float:
        if not self.real or not self.real.records:
            return 50.0
        return float(np.median([r["supply_freq_hz"] for r in self.real.records]))

    def base_sim_config(self, **kw) -> SD.SimConfig:
        cfg = SD.SimConfig(supply_freq_hz=self.supply_freq(), seconds=self.sim_seconds)
        return dataclasses.replace(cfg, **kw)

    def sim_table(self, labels: list[str], cfg: SD.SimConfig, seed: int, runs: int | None = None) -> T.FeatureTable:
        runs = runs or self.sim_runs_per_class
        key = T.cache_key({"v": CACHE_VERSION, "labels": labels, "cfg": cfg.describe(), "seed": seed,
                           "runs": runs, "axes": list(self.axes)})
        if key in self._sim_cache:
            return self._sim_cache[key]
        path = (self.cache_dir / f"sim_{key}.npz") if self.cache_dir else None
        if path and path.exists():
            tab = T.load(path)
        else:
            log.info("simulating %d runs x %d classes (%s)", runs, len(labels), cfg.label)
            tab = T.build(SD.generate(labels, runs, cfg, seed), axes=self.axes)
            if path:
                T.save(tab, path)
        self._sim_cache[key] = tab
        return tab

    def writer(self, experiment: str, extra: dict) -> R.ExperimentWriter:
        meta = {**self.run_meta, "seeds": self.seeds, "model": self.model_kind,
                "sim_runs_per_class": self.sim_runs_per_class, "sim_seconds": self.sim_seconds, **extra}
        if self.real is not None:
            meta["channels_evaluated"] = T.channel_report(self.real)
            meta["n_real_recordings"] = len(self.real.records)
            meta["skipped_recordings"] = self.real.skipped[:50]
        return R.ExperimentWriter(self.out_root, self.dataset, experiment, meta)


def _record_eval(fitted: MD.Fitted, X, y, g) -> tuple[dict, np.ndarray, np.ndarray]:
    """Recording-level metrics (window probabilities averaged per recording)."""
    ug, proba = fitted.record_proba(X, g)
    lab = {gg: yy for gg, yy in zip(g, y, strict=True)}
    y_true = np.array([lab[gg] for gg in ug], dtype=object)
    y_pred = np.array(fitted.classes, dtype=object)[proba.argmax(1)]
    return M.classification(y_true, y_pred, proba, fitted.classes), y_true, proba


def _flat(view: str, seed: int, m: dict, **extra) -> dict:
    row = {"view": view, "seed": seed, **extra}
    for k in ("n", "accuracy", "macro_f1", "auroc_healthy_vs_fault", "ece", "brier"):
        row[k] = m.get(k, float("nan"))
    row["per_class_recall"] = m.get("per_class_recall", {})
    return row


KEYS = ["accuracy", "macro_f1", "auroc_healthy_vs_fault", "ece", "brier"]


def _need_real(ctx: Context, name: str) -> None:
    if ctx.real is None:
        raise ValueError(f"protocol {name} needs a real dataset (--dataset bruinsma|liman_c|estogu|usp_brb)")


# ======================================================================================= 1
def sim_baseline(ctx: Context) -> Path:
    classes = ctx.common_classes() if ctx.real is not None else sorted(TWIN_LABELS)
    rows, confusion = [], None
    for seed in ctx.seeds:
        tab = ctx.sim_table(classes, ctx.base_sim_config(label="nominal"), seed)
        for view in ctx.views():
            X, y, g = tab.X[view], tab.y[view], tab.groups[view]
            tr, te = S.group_holdout(g, y, ctx.test_fraction, seed)
            f = MD.fit(ctx.model_kind, X[tr], y[tr], classes, seed)
            m, _, _ = _record_eval(f, X[te], y[te], g[te])
            rows.append(_flat(view, seed, m, train_runs=len(set(g[tr])), test_runs=len(set(g[te]))))
            if seed == ctx.seeds[0] and view == ctx.views()[0]:
                confusion = (m["confusion"], classes)
    summary = R.mean_std(rows, KEYS, ["view"])
    convbilstm = _convbilstm_reference()
    w = ctx.writer("sim_baseline", {
        "split": f"label-stratified group holdout on simulated runs, test_fraction={ctx.test_fraction}",
        "classes": classes, "convbilstm_reference": convbilstm,
        "note": "Simulator-only. High accuracy here shows the simulated signatures are separable, nothing more.",
    })
    if confusion:
        R.confusion_png(w.dir / "confusion.png", *confusion, f"sim test ({ctx.views()[0]}, seed {ctx.seeds[0]})")
    if convbilstm:
        summary.append({"view": "conv_bilstm (existing artifact, 6 classes, vib+acoustic)",
                        "accuracy_mean": convbilstm.get("accuracy_mean", float("nan")),
                        "accuracy_std": convbilstm.get("accuracy_std", float("nan")),
                        "macro_f1_mean": convbilstm.get("macro_f1_mean", float("nan")),
                        "macro_f1_std": convbilstm.get("macro_f1_std", float("nan"))})
    return w.finish(rows, ["view", "accuracy_mean", "macro_f1_mean", "auroc_healthy_vs_fault_mean", "ece_mean",
                           "brier_mean"], "Simulation-only baseline (recording-level, mean $\\pm$ std over seeds).",
                    summary)


def _convbilstm_reference() -> dict | None:
    p = Path(__file__).resolve().parents[1] / "diagnostics" / "ml" / "artifacts" / "metrics.json"
    if not p.exists():
        return None
    m = json.loads(p.read_text())
    return {k: m.get(k) for k in ("accuracy_mean", "accuracy_std", "macro_f1_mean", "macro_f1_std",
                                   "protocol", "runs_per_class", "classes")} | {
        "reproduce": "python -m app.diagnostics.ml.train --runs-per-class 40 --seeds 0 1 2"}


# ======================================================================================= 2
def _zero_shot_rows(ctx: Context, cfg: SD.SimConfig, tag: str, real_idx: dict[str, list] | None = None):
    """Train on simulator data with `cfg`, test on real. Returns (rows, first confusion)."""
    classes = ctx.common_classes()
    rows, confusion = [], None
    for seed in ctx.seeds:
        tab = ctx.sim_table(classes, cfg, seed)
        for view in ctx.views():
            if not tab.has(view):
                continue
            X, y, g = tab.X[view], tab.y[view], tab.groups[view]
            tr, te = S.group_holdout(g, y, ctx.test_fraction, seed)
            f = MD.fit(ctx.model_kind, X[tr], y[tr], classes, seed)
            m_sim, _, _ = _record_eval(f, X[te], y[te], g[te])
            Xr, yr, gr = ctx.rt.subset(view, set(classes))
            if real_idx is not None:
                keep = np.isin(gr, list(real_idx.get(view, [])))
                Xr, yr, gr = Xr[keep], yr[keep], gr[keep]
            if not len(Xr):
                continue
            m_real, _, _ = _record_eval(f, Xr, yr, gr)
            # out-of-scope recordings: healthy-vs-anomaly only
            auroc_oos = _oos_auroc(ctx, f, view, set(classes))
            gap = M.gap(m_sim, m_real)
            row = _flat(view, seed, m_real, setting=tag, sim_accuracy=m_sim["accuracy"],
                        sim_macro_f1=m_sim["macro_f1"], auroc_incl_out_of_scope=auroc_oos)
            row.update({f"gap_{k}": v for k, v in gap.items()})
            rows.append(row)
            if confusion is None:
                confusion = (m_real["confusion"], classes, view)
    return rows, confusion


def _oos_auroc(ctx: Context, f: MD.Fitted, view: str, classes: set[str]) -> float:
    oos = {r["group"] for r in ctx.rt.records if r["label"] == OUT_OF_SCOPE}
    if not oos or HEALTHY not in f.classes:
        return float("nan")
    m = np.isin(ctx.rt.y[view], list(classes)) | np.isin(ctx.rt.groups[view], list(oos))
    X, g = ctx.rt.X[view][m], ctx.rt.groups[view][m]
    ug, proba = f.record_proba(X, g)
    lab = ctx.rt.record_labels()
    is_anom = np.array([lab[x] != HEALTHY for x in ug]).astype(int)
    if is_anom.min() == is_anom.max():
        return float("nan")
    from sklearn.metrics import roc_auc_score

    return float(roc_auc_score(is_anom, 1 - proba[:, f.classes.index(HEALTHY)]))


ZS_COLS = ["setting", "view", "accuracy_mean", "macro_f1_mean", "auroc_healthy_vs_fault_mean", "ece_mean",
           "brier_mean", "gap_accuracy_mean", "gap_macro_f1_mean"]
ZS_KEYS = KEYS + ["gap_accuracy", "gap_macro_f1", "gap_auroc_healthy_vs_fault", "gap_ece", "gap_brier",
                  "sim_accuracy", "auroc_incl_out_of_scope"]


def zero_shot(ctx: Context) -> Path:
    _need_real(ctx, "zero_shot")
    rows, confusion = _zero_shot_rows(ctx, ctx.base_sim_config(label="nominal"), "nominal simulator")
    w = ctx.writer("zero_shot", {
        "split": "train: all simulated runs of the common classes (sim gap reference: grouped sim holdout); "
                 "test: every real recording of the common classes",
        "classes": ctx.common_classes(),
        "out_of_scope": "real out-of-scope classes enter only auroc_incl_out_of_scope (healthy vs anomaly)",
        "gap_definition": "metric(sim test) - metric(real test)",
    })
    if confusion:
        R.confusion_png(w.dir / "confusion.png", confusion[0], confusion[1],
                        f"zero-shot sim->real ({confusion[2]}, seed {ctx.seeds[0]})")
    return w.finish(rows, ZS_COLS, "Zero-shot sim-to-real (recording level, mean $\\pm$ std over seeds).",
                    R.mean_std(rows, ZS_KEYS, ["setting", "view"]))


# ======================================================================================= 3
def real_only(ctx: Context) -> Path:
    _need_real(ctx, "real_only")
    classes = ctx.common_classes()
    rows, notes = [], []
    motor_of = {r["group"]: r["motor_group"] for r in ctx.rt.records}
    for view in ctx.views():
        X, y, g = ctx.rt.subset(view, set(classes))
        motors = np.array([motor_of[x] for x in g], dtype=object)
        # leave-one-motor-group-out, only folds whose test classes all occur in training
        for tr, te, held in S.leave_one_group_out(motors):
            test_classes = set(y[te])
            if not test_classes <= set(y[tr]):
                notes.append(f"{view}: LOMO fold '{held}' skipped -- its classes {sorted(test_classes - set(y[tr]))} "
                             "exist only in that motor group (class/motor confound)")
                continue
            for seed in ctx.seeds:
                f = MD.fit(ctx.model_kind, X[tr], y[tr], classes, seed)
                m, _, _ = _record_eval(f, X[te], y[te], g[te])
                rows.append(_flat(view, seed, m, scheme="leave-one-motor-group-out", fold=held))
        for seed in ctx.seeds:
            for k, (tr, te) in enumerate(S.grouped_kfold(g, y, 5, seed)):
                f = MD.fit(ctx.model_kind, X[tr], y[tr], classes, seed)
                m, _, _ = _record_eval(f, X[te], y[te], g[te])
                rows.append(_flat(view, seed, m, scheme="grouped 5-fold by recording", fold=k))
    if len({r["motor_group"] for r in ctx.rt.records}) == len(classes):
        notes.append("every class comes from its own motor group: grouped-by-recording CV may learn the motor, "
                     "not the fault -- treat these numbers as an upper bound")
    w = ctx.writer("real_only", {"split": "leave-one-motor-group-out (where feasible) and label-stratified grouped "
                                          "5-fold by recording", "classes": classes, "notes": notes})
    return w.finish(rows, ["scheme", "view", "accuracy_mean", "macro_f1_mean", "auroc_healthy_vs_fault_mean",
                           "ece_mean", "brier_mean"], "Real-only baselines (recording level).",
                    R.mean_std(rows, KEYS, ["scheme", "view"]))


# ======================================================================================= 4
def few_shot(ctx: Context) -> Path:
    _need_real(ctx, "few_shot")
    classes = ctx.common_classes()
    rows = []
    for seed in ctx.seeds:
        rng = np.random.default_rng(seed)
        sim = ctx.sim_table(classes, ctx.base_sim_config(label="nominal"), seed)
        for view in ctx.views():
            if not sim.has(view):
                continue
            X, y, g = ctx.rt.subset(view, set(classes))
            pool_i, test_i = S.group_holdout(g, y, ctx.test_fraction, seed)
            pre = MD.fit("mlp", sim.X[view], sim.y[view], classes, seed)
            m0, _, _ = _record_eval(pre, X[test_i], y[test_i], g[test_i])
            rows.append(_flat(view, seed, m0, k=0, method="sim pre-trained (zero-shot)"))
            pool_groups = {c: sorted(set(g[pool_i][y[pool_i] == c])) for c in classes}
            for k in ctx.ks:
                chosen = []
                for c in classes:
                    gs = list(pool_groups[c])
                    rng.shuffle(gs)
                    chosen += gs[:k]
                idx = pool_i[np.isin(g[pool_i], chosen)]
                if not len(idx):
                    continue
                avail = min(len(pool_groups[c]) for c in classes)
                ft = MD.fine_tune(pre, X[idx], y[idx])
                m_ft, _, _ = _record_eval(ft, X[test_i], y[test_i], g[test_i])
                rows.append(_flat(view, seed, m_ft, k=k, method="sim pre-train + fine-tune", k_effective=min(k, avail)))
                if len(set(y[idx])) >= 2:
                    ro = MD.fit("mlp", X[idx], y[idx], classes, seed)
                    m_ro, _, _ = _record_eval(ro, X[test_i], y[test_i], g[test_i])
                    rows.append(_flat(view, seed, m_ro, k=k, method="real-only", k_effective=min(k, avail)))
    summary = R.mean_std(rows, KEYS, ["view", "method", "k"])
    w = ctx.writer("few_shot", {"split": "real: label-stratified group holdout (test) + pool; k recordings per "
                                         "class drawn from the pool; MLP (64,32); fine-tuning keeps the sim scaler",
                                "ks": list(ctx.ks), "classes": classes})
    for view in ctx.views():
        series = {}
        for method in ("sim pre-train + fine-tune", "real-only"):
            pts = sorted((r["k"], r["accuracy_mean"], r["accuracy_std"]) for r in summary
                         if r["view"] == view and r["method"] == method)
            if pts:
                series[method] = ([p[1] for p in pts], [p[2] for p in pts])
                xs = [p[0] for p in pts]
        zs = [r["accuracy_mean"] for r in summary if r["view"] == view and r["k"] == 0]
        if series:
            R.lines_png(w.dir / f"few_shot_{view}.png", xs, series, "real recordings per class (k)",
                        "recording accuracy", f"Few-shot adaptation ({view})",
                        ("zero-shot", zs[0]) if zs else None)
    return w.finish(rows, ["view", "method", "k", "accuracy_mean", "macro_f1_mean"],
                    "Few-shot adaptation vs real-only training (mean $\\pm$ std over seeds).", summary)


# ======================================================================================= 5
def domain_shift(ctx: Context) -> Path:
    _need_real(ctx, "domain_shift")
    classes = ctx.common_classes()
    seed = ctx.seeds[0]
    sim = ctx.sim_table(classes, ctx.base_sim_config(label="nominal"), seed)
    rows, feat_rows = [], []
    w = ctx.writer("domain_shift", {"split": "all simulated runs vs all real recordings per class (no training "
                                             "involved except the grouped-CV classifier two-sample test)",
                                    "classes": classes,
                                    "metrics": "MMD^2 (RBF, median bandwidth, standardised); 1-D Wasserstein on "
                                               "pooled-standardised features; C2ST = grouped 5-fold logistic AUROC"})
    for view in ctx.views():
        names = FT.feature_names(view, ctx.axes)
        wsum = np.zeros(len(names))
        for c in classes:
            xs, _, gs = sim.subset(view, {c})
            xr, _, gr = ctx.rt.subset(view, {c})
            if len(xs) < 4 or len(xr) < 4:
                continue
            xs, xr = np.nan_to_num(xs), np.nan_to_num(xr)
            wd = M.wasserstein_per_feature(xs, xr)
            wsum += wd
            rows.append({"view": view, "class": c, "mmd2": M.mmd_rbf(xs, xr, seed=seed),
                         "c2st_auc": M.c2st_auc(xs, xr, gs, gr, seed=seed),
                         "mean_wasserstein": float(wd.mean()), "n_sim": len(xs), "n_real": len(xr)})
            for j in np.argsort(wd)[::-1][:10]:
                feat_rows.append({"view": view, "class": c, "feature": names[j], "wasserstein": float(wd[j])})
        if wsum.any():
            order = np.argsort(wsum)[::-1][:15]
            R.bars_png(w.dir / f"top_shifted_features_{view}.png", [names[j] for j in order],
                       [float(wsum[j] / len(classes)) for j in order], "mean Wasserstein (standardised)",
                       f"Most-shifted features, sim vs real ({view})")
    R.write_csv(w.dir / "feature_ranking.csv", feat_rows)
    sb = _sideband_table(ctx, sim)
    R.write_csv(w.dir / "mcsa_sidebands.csv", sb)
    w.meta["mcsa_sidebands"] = ("BRB lines f(1 +/- 2s) and eccentricity lines f +/- fr in dB relative to the "
                                "fundamental, median per load bin; real slip from the current spectrum (approx.)")
    return w.finish(rows, ["view", "class", "mmd2", "c2st_auc", "mean_wasserstein", "n_sim", "n_real"],
                    "Domain shift between simulated and real features per class.")


def _sideband_table(ctx: Context, sim: T.FeatureTable) -> list[dict]:
    if not (ctx.rt.has("current") and sim.has("current")):
        return []
    names = FT.CURRENT_FEATURES
    out = []
    rec_r = {r["group"]: r for r in ctx.rt.records}
    rec_s = {r["group"]: r for r in sim.records}
    for c in sorted(set(ctx.common_classes()) & {"broken_rotor_bar", HEALTHY, "eccentricity"}):
        for lo, hi in ((0, 37.5), (37.5, 62.5), (62.5, 87.5), (87.5, 200)):
            def pick(tab, recs, c=c, lo=lo, hi=hi):
                m = tab.y["current"] == c
                ok = np.array([lo <= (recs[g]["load_pct"] if recs[g]["load_pct"] is not None else 75.0) < hi
                               for g in tab.groups["current"][m]], dtype=bool)
                return tab.X["current"][m][ok]
            xr, xs = pick(ctx.real, rec_r), pick(sim, rec_s)
            if not len(xr) or not len(xs):
                continue
            for feat in ("brb_lsb_db", "brb_usb_db", "ecc_lsb_db", "ecc_usb_db"):
                j = names.index(feat)
                out.append({"class": c, "load_bin_pct": f"{lo}-{hi}", "line": feat,
                            "real_median_db": float(np.median(xr[:, j])), "sim_median_db": float(np.median(xs[:, j])),
                            "real_minus_sim_db": float(np.median(xr[:, j]) - np.median(xs[:, j])),
                            "n_real_windows": len(xr), "n_sim_windows": len(xs)})
    return out


# ======================================================================================= 6
def calibration(ctx: Context) -> Path:
    _need_real(ctx, "calibration")
    classes = ctx.common_classes()
    rows, cal_meta = [], []
    for seed in ctx.seeds:
        # split real recordings: calibration only sees healthy TRAIN recordings
        g_all = np.array([r["group"] for r in ctx.rt.records], dtype=object)
        y_all = np.array([r["label"] for r in ctx.rt.records], dtype=object)
        keep = np.isin(y_all, classes)
        tr, te = S.group_holdout(g_all[keep], y_all[keep], ctx.test_fraction, seed)
        train_groups, test_groups = set(g_all[keep][tr]), set(g_all[keep][te])
        healthy_train = {g for g in train_groups if ctx.rt.record_labels()[g] == HEALTHY}
        prepared = [prepare(r) for r in _iter_groups(ctx, healthy_train)]
        cal = CAL.fit(prepared)
        nominal = ctx.sim_table(classes, ctx.base_sim_config(params=cal.params, noise_current_a=cal.noise_current_a,
                                                             noise_vib=cal.noise_vib, label=f"cal-nominal-{seed}",
                                                             severity_range=(0.6, 0.6)), seed, runs=4)
        train_tab = _subset_table(ctx.rt, train_groups)
        gains = CAL.severity_gains(train_tab, nominal)
        cal.severity_gain = gains
        cal_meta.append({"seed": seed, **cal.describe()})
        cfg = ctx.base_sim_config(params=cal.params, noise_current_a=cal.noise_current_a, noise_vib=cal.noise_vib,
                                  severity_gain=gains, label=f"calibrated-{seed}")
        test_idx = {v: list(test_groups) for v in ctx.views()}
        before, _ = _zero_shot_rows(_one_seed(ctx, seed), ctx.base_sim_config(label="nominal"), "nominal", test_idx)
        after, _ = _zero_shot_rows(_one_seed(ctx, seed), cfg, "calibrated", test_idx)
        rows += before + after
    summary = R.mean_std(rows, ZS_KEYS, ["setting", "view"])
    _gap_closure(summary)
    w = ctx.writer("calibration", {"split": "label-stratified group holdout of real recordings; calibration fitted "
                                            "on HEALTHY TRAIN recordings only; both models tested on the same real test split",
                                   "calibration": cal_meta})
    return w.finish(rows, ["setting", "view", "accuracy_mean", "macro_f1_mean", "gap_accuracy_mean",
                           "gap_closure_accuracy"], "Effect of simulator calibration on the sim-to-real gap.", summary)


def _gap_closure(summary: list[dict]) -> None:
    by = {(r["setting"], r["view"]): r for r in summary}
    for (setting, view), r in by.items():
        base = by.get(("nominal", view)) or by.get(("nominal simulator", view))
        if setting != "nominal" and base and base.get("gap_accuracy_mean") not in (None, 0.0):
            r["gap_closure_accuracy"] = 1 - r["gap_accuracy_mean"] / base["gap_accuracy_mean"]


def _one_seed(ctx: Context, seed: int) -> Context:
    return dataclasses.replace(ctx, seeds=[seed], _sim_cache=ctx._sim_cache)


def _iter_groups(ctx: Context, groups: set[str]):
    if ctx.loader is None:
        raise ValueError("this protocol re-reads raw signals and needs the dataset loader")
    for rec in ctx.loader.iter_records():
        if rec.group_key in groups:
            yield rec


def _subset_table(t: T.FeatureTable, groups: set[str]) -> T.FeatureTable:
    X, y, g = {}, {}, {}
    for v in t.X:
        m = np.isin(t.groups[v], list(groups))
        X[v], y[v], g[v] = t.X[v][m], t.y[v][m], t.groups[v][m]
    return T.FeatureTable(X, y, g, [r for r in t.records if r["group"] in groups], [], t.axes)


# ======================================================================================= 7
def domain_randomisation(ctx: Context) -> Path:
    _need_real(ctx, "domain_randomisation")
    rows, _ = _zero_shot_rows(ctx, ctx.base_sim_config(label="nominal"), "nominal")
    dr, _ = _zero_shot_rows(ctx, ctx.base_sim_config(randomise=True, label="randomised"), "domain-randomised")
    rows += dr
    summary = R.mean_std(rows, ZS_KEYS, ["setting", "view"])
    _gap_closure(summary)
    w = ctx.writer("domain_randomisation", {"split": "as zero_shot", "randomisation_ranges": SD.__doc__})
    return w.finish(rows, ["setting", "view", "accuracy_mean", "macro_f1_mean", "auroc_healthy_vs_fault_mean",
                           "gap_accuracy_mean", "gap_closure_accuracy"],
                    "Zero-shot performance with and without domain randomisation.", summary)


# ======================================================================================= 8
DOMAIN = {"electrical": {"broken_rotor_bar", "interturn_short", "eccentricity"},
          "mechanical": {"bearing", "unbalance", "misalignment"}}


def _fuse(pe: np.ndarray, pm: np.ndarray, classes: list[str]) -> np.ndarray:
    """Twin fusion weights: authoritative channel 1.0, other 0.3 per fault domain; healthy 1.0 / 1.0."""
    we = np.array([1.0 if c in DOMAIN["electrical"] else 0.3 if c in DOMAIN["mechanical"] else 1.0 for c in classes])
    wm = np.array([1.0 if c in DOMAIN["mechanical"] else 0.3 if c in DOMAIN["electrical"] else 1.0 for c in classes])
    p = we * pe + wm * pm
    return p / p.sum(1, keepdims=True)


def channel_ablation(ctx: Context) -> Path:
    _need_real(ctx, "channel_ablation")
    classes = ctx.common_classes()
    if not (ctx.rt.has("current") and ctx.rt.has("vibration")):
        w = ctx.writer("channel_ablation", {"skipped": "needs both current and vibration in the real dataset"})
        return w.finish([{"result": "not evaluable: dataset lacks current or vibration"}], ["result"],
                        "Channel ablation not evaluable on this dataset.")
    rows = []
    for seed in ctx.seeds:
        sim = ctx.sim_table(classes, ctx.base_sim_config(label="nominal"), seed)
        for setting in ("zero-shot (sim-trained)", "real-only (grouped holdout)"):
            if setting.startswith("zero"):
                fe = MD.fit(ctx.model_kind, sim.X["current"], sim.y["current"], classes, seed)
                fm = MD.fit(ctx.model_kind, sim.X["vibration"], sim.y["vibration"], classes, seed)
                test_groups = None
            else:
                ge = np.array([r["group"] for r in ctx.rt.records if r["label"] in classes], dtype=object)
                ye = np.array([r["label"] for r in ctx.rt.records if r["label"] in classes], dtype=object)
                tr, te = S.group_holdout(ge, ye, ctx.test_fraction, seed)
                trg, test_groups = set(ge[tr]), set(ge[te])
                fits = []
                for v in ("current", "vibration"):
                    X, y, g = ctx.rt.subset(v, set(classes))
                    m = np.isin(g, list(trg))
                    fits.append(MD.fit(ctx.model_kind, X[m], y[m], classes, seed))
                fe, fm = fits
            preds = {}
            for name, f, v in (("electrical", fe, "current"), ("ml", fm, "vibration")):
                X, y, g = ctx.rt.subset(v, set(classes))
                if test_groups is not None:
                    m = np.isin(g, list(test_groups))
                    X, y, g = X[m], y[m], g[m]
                ug, p = f.record_proba(X, g)
                preds[name] = dict(zip(ug, p, strict=True))
            common = sorted(set(preds["electrical"]) & set(preds["ml"]))
            lab = ctx.rt.record_labels()
            y_true = np.array([lab[g] for g in common], dtype=object)
            for name, p in (("electrical only", np.array([preds["electrical"][g] for g in common])),
                            ("ML only", np.array([preds["ml"][g] for g in common])),
                            ("fused", _fuse(np.array([preds["electrical"][g] for g in common]),
                                            np.array([preds["ml"][g] for g in common]), classes))):
                y_pred = np.array(classes, dtype=object)[p.argmax(1)]
                rows.append(_flat(name, seed, M.classification(y_true, y_pred, p, classes), setting=setting))
    summary = R.mean_std(rows, KEYS, ["setting", "view"])
    for s in {r["setting"] for r in summary}:
        acc = {r["view"]: r["accuracy_mean"] for r in summary if r["setting"] == s}
        best_single = max(acc.get("electrical only", float("nan")), acc.get("ML only", float("nan")))
        for r in summary:
            if r["setting"] == s and r["view"] == "fused":
                r["fusion_minus_best_single"] = acc.get("fused", float("nan")) - best_single
    w = ctx.writer("channel_ablation", {"fusion": "probability-level, twin domain weights (authoritative 1.0, "
                                                  "other 0.3; healthy 1.0/1.0)", "classes": classes})
    return w.finish(rows, ["setting", "view", "accuracy_mean", "macro_f1_mean", "auroc_healthy_vs_fault_mean",
                           "fusion_minus_best_single"], "Channel ablation: does fusion help on real data?", summary)


# ======================================================================================= 9
def thresholds(ctx: Context) -> Path:
    _need_real(ctx, "thresholds")
    from app.diagnostics.calibration import BRB_DBC_MIN
    from app.simulation.params import DEFAULT_MOTOR

    rows = []
    labels = ctx.rt.record_labels()
    groups = np.array(sorted(labels), dtype=object)
    ylab = np.array([labels[g] for g in groups], dtype=object)
    for seed in ctx.seeds:
        tr, va, te = S.group_holdout(groups, ylab, ctx.test_fraction, seed, val_fraction=ctx.val_fraction)
        tr_g, va_g, te_g = set(groups[tr]), set(groups[va]), set(groups[te])
        # --- MCSA BRB threshold (works on current-only data) ---
        if ctx.rt.has("current"):
            j = [FT.CURRENT_FEATURES.index("brb_lsb_db"), FT.CURRENT_FEATURES.index("brb_usb_db")]
            X, y, g = ctx.rt.X["current"], ctx.rt.y["current"], ctx.rt.groups["current"]
            score = X[:, j].max(1)
            rows += _threshold_rows("MCSA BRB sideband (dBc)", BRB_DBC_MIN, score, y, g, va_g, te_g, seed,
                                    positive="broken_rotor_bar")
        # --- residual FD and supply checks (need voltage) ---
        has_v = any({"va", "vb", "vc"} <= set(r["signals"]) for r in ctx.rt.records)
        if has_v:
            healthy_train = {x for x in tr_g if labels[x] == HEALTHY}
            prepared_train = [prepare(r) for r in _iter_groups(ctx, healthy_train)]
            cal = CAL.fit(prepared_train)
            v_nom = float(np.median([abs(CAL.phasor(p.elec["va"][: int(2 * 5000)], p.supply_freq_hz))
                                     for p in prepared_train if "va" in p.elec])) if prepared_train else None
            fd: dict[str, tuple[list, list, list]] = {}
            sup_flags: list[bool] = []
            for rec in _iter_groups(ctx, va_g | te_g):
                p = prepare(rec)
                for pname, params in (("default", DEFAULT_MOTOR), ("calibrated", cal.params)):
                    for mode in ("slip from current spectrum", "sensorless slip fit (optimistic)"):
                        slip = TC.sensorless_slip(p, params) if mode.startswith("sensorless") else None
                        vals = TC.residual_fd(p, params, slip=slip)
                        key = f"residual FD_norm ({pname} params, {mode})"
                        acc = fd.setdefault(key, ([], [], []))
                        acc[0].extend(vals)
                        acc[1].extend([rec.label] * len(vals))
                        acc[2].extend([rec.group_key] * len(vals))
                if rec.label == HEALTHY and rec.group_key in te_g and v_nom:
                    sup_flags += TC.supply_flags(p, v_nom)
            for name, (vals, ys, gs) in fd.items():
                if vals:
                    rows += _threshold_rows(name, TC.FD_THRESHOLD, np.array(vals),
                                            np.array(ys, dtype=object), np.array(gs, dtype=object), va_g, te_g, seed)
            if sup_flags:
                rows.append({"seed": seed, "detector": "supply VUF/THD/sag", "threshold_kind": "twin limits",
                             "threshold": "EN 50160 limits", "false_alarm_rate": float(np.mean(sup_flags)),
                             "detection_rate": float("nan"), "n_healthy_windows": len(sup_flags)})
    summary = R.mean_std(rows, ["false_alarm_rate", "detection_rate", "threshold"], ["detector", "threshold_kind"])
    w = ctx.writer("thresholds", {
        "split": f"real recordings: label-stratified group holdout train/val/test "
                 f"({1 - ctx.test_fraction - ctx.val_fraction:.0%}/{ctx.val_fraction:.0%}/{ctx.test_fraction:.0%}); "
                 "re-tuned threshold = 99th percentile of the healthy VALIDATION windows; rates on TEST windows; "
                 "calibrated params fitted on healthy TRAIN recordings",
        "speed": "no encoder in the public datasets: the residual is run with speed = synchronous x (1 - slip), "
                 "slip either estimated from the current spectrum or fitted to minimise the residual (sensorless, "
                 "optimistic: also absorbs fault signatures). FD is very sensitive to the speed estimate."})
    return w.finish(rows, ["detector", "threshold_kind", "threshold_mean", "false_alarm_rate_mean",
                           "detection_rate_mean"], "Twin thresholds on real data: false alarms as-is and re-tuned.",
                    summary)


def _threshold_rows(name, thr, score, y, g, va_g, te_g, seed, positive: str | None = None) -> list[dict]:
    score = np.asarray(score, float)
    healthy = np.asarray(y) == HEALTHY
    is_va, is_te = np.isin(g, list(va_g)), np.isin(g, list(te_g))
    pos = (np.asarray(y) == positive) if positive else ~healthy
    out = []
    va_h = score[healthy & is_va]
    retuned = float(np.percentile(va_h, 99)) if len(va_h) >= 5 else float("nan")
    for kind, t in (("twin default", thr), ("re-tuned (val p99)", retuned)):
        te_h, te_p = score[healthy & is_te], score[pos & is_te]
        out.append({"seed": seed, "detector": name, "threshold_kind": kind, "threshold": float(t),
                    "false_alarm_rate": float(np.mean(te_h > t)) if len(te_h) and np.isfinite(t) else float("nan"),
                    "detection_rate": float(np.mean(te_p > t)) if len(te_p) and np.isfinite(t) else float("nan"),
                    "n_healthy_windows": int(len(te_h)), "n_fault_windows": int(len(te_p))})
    return out


# ======================================================================================= 10
def severity(ctx: Context) -> Path:
    _need_real(ctx, "severity")
    rows = []
    recs = ctx.rt.records
    for c in sorted({r["label"] for r in recs if r["label"] not in (HEALTHY, OUT_OF_SCOPE)}):
        sel = [r for r in recs if r["label"] == c and r["severity"] is not None]
        healthy = [r for r in recs if r["label"] == HEALTHY]
        levels = {r["severity"] for r in sel}
        include_healthy = len(levels) < 2 and bool(healthy)
        pool = sel + (healthy if include_healthy or c == "broken_rotor_bar" else [])
        scores, lv, method = [], [], ""
        for r in pool:
            cur = _mean_rows(ctx.rt, "current", r["group"])
            vib = _mean_rows(ctx.rt, "vibration", r["group"])
            s, method_r = TC.twin_severity(c, cur, vib, ctx.axes)
            if s is None:
                continue
            method = method_r
            scores.append(s)
            lv.append(0.0 if r["label"] == HEALTHY else float(r["severity"]))
        if len(set(lv)) < 2:
            rows.append({"class": c, "result": "fewer than 2 severity levels -- not evaluable", "method": method})
            continue
        res = M.spearman_monotonic(scores, lv)
        rows.append({"class": c, "method": method, "n_recordings": len(scores),
                     "levels": sorted(set(lv)), "spearman_rho": res["spearman_rho"], "p_value": res["p_value"],
                     "monotonic": res["monotonic"], "level_means": res["level_means"]})
    w = ctx.writer("severity", {
        "rul": "NOT validated: no public dataset used here has run-to-failure labels. Remaining-life outputs of "
               "the twin are validated only for severity RANKING (this table) and for simulated degradation.",
        "levels": "dataset severity levels (e.g. number of broken bars, Bruinsma severity level); healthy = 0"})
    return w.finish(rows, ["class", "method", "n_recordings", "spearman_rho", "p_value", "monotonic"],
                    "Twin severity score vs true severity level (Spearman). RUL accuracy is not claimed.")


def _mean_rows(t: T.FeatureTable, view: str, group: str) -> np.ndarray | None:
    if not t.has(view):
        return None
    m = t.groups[view] == group
    return np.nanmean(t.X[view][m], axis=0) if m.any() else None


PROTOCOLS: dict[str, Callable[[Context], Path]] = {
    "sim_baseline": sim_baseline,
    "zero_shot": zero_shot,
    "real_only": real_only,
    "few_shot": few_shot,
    "domain_shift": domain_shift,
    "calibration": calibration,
    "domain_randomisation": domain_randomisation,
    "channel_ablation": channel_ablation,
    "thresholds": thresholds,
    "severity": severity,
}
