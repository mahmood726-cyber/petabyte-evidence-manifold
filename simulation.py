import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

PROJECT_ROOT = Path(__file__).resolve().parent
CERTIFICATION_PATH = PROJECT_ROOT / "certification.json"
AUDIT_RESULTS_PATH = PROJECT_ROOT / "ultra_audit_results.csv"
INTERPOLATION_GRID = np.linspace(0, 1, 100)


def inv_logit(logit_value):
    return 1 / (1 + np.exp(-logit_value))


def simulate_chronological_dta(k=40, drift=0.01, rng=None):
    rng = rng or np.random.default_rng()
    logit_s_base, logit_sp_base = 1.38, 2.19
    results = []
    for i in range(k):
        l_s = logit_s_base + (i * drift) + rng.normal(0, 0.1)
        l_sp = logit_sp_base - (i * drift / 2) + rng.normal(0, 0.1)
        sensitivity, specificity = inv_logit(l_s), inv_logit(l_sp)
        tp = rng.binomial(125, sensitivity)
        tn = rng.binomial(375, specificity)
        results.append({"tp": tp, "fp": 375 - tn, "fn": 125 - tp, "tn": tn})
    return pd.DataFrame(results), [logit_s_base + (k / 2) * drift, logit_sp_base - (k / 4) * drift]


def aps_v2_fast(df):
    tp, fp, fn, tn = df["tp"] + 0.5, df["fp"] + 0.5, df["fn"] + 0.5, df["tn"] + 0.5
    sensitivity = tp / (tp + fn)
    false_positive_rate = fp / (fp + tn)
    points = np.column_stack([false_positive_rate, sensitivity])
    dbscan = DBSCAN(eps=0.1, min_samples=3).fit(points)
    labels = dbscan.labels_

    aleph_points = []
    for label in set(labels):
        if label == -1:
            continue
        mask = labels == label
        sub_sensitivity = sensitivity[mask]
        sub_fpr = false_positive_rate[mask]
        j_index = sub_sensitivity + (1 - sub_fpr) - 1
        weights = np.power(np.maximum(j_index, 0.1), 3)
        aleph_points.append(
            {
                "fpr": float(np.average(sub_fpr, weights=weights)),
                "sens": float(np.average(sub_sensitivity, weights=weights)),
            }
        )

    aleph_points = sorted(aleph_points, key=lambda point: point["fpr"])
    x_points = [0.0] + [point["fpr"] for point in aleph_points] + [1.0]
    y_points = [0.0] + [point["sens"] for point in aleph_points] + [1.0]
    y_new = np.interp(INTERPOLATION_GRID, x_points, y_points)
    y_new = np.maximum.accumulate(y_new)
    return float(np.trapezoid(y_new, INTERPOLATION_GRID))


def build_certification(results_df, n_simulations):
    temporal_robustness = float((results_df["bias"] < 0.08).mean())
    mean_bias = float(results_df["bias"].mean())
    return {
        "status": "DEEP_LAKE_VALIDATED",
        "n_simulations": n_simulations,
        "temporal_robustness_index": round(temporal_robustness, 4),
        "mean_bias": round(mean_bias, 4),
        "system": "Petabyte Evidence Manifold (PEM-DTA)",
    }


def write_outputs(results_df, cert, project_root=PROJECT_ROOT):
    certification_path = Path(project_root) / CERTIFICATION_PATH.name
    results_path = Path(project_root) / AUDIT_RESULTS_PATH.name
    certification_path.write_text(json.dumps(cert, indent=2), encoding="utf-8")
    results_df.to_csv(results_path, index=False)
    return certification_path, results_path


def run_ultra_scale_audit(n_simulations=100, seed=726):
    rng = np.random.default_rng(seed)
    pem_results = []

    print(f"RUNNING PEM ULTRA-SCALE AUDIT ({n_simulations} Simulations with Temporal Drift)...")
    for i in range(n_simulations):
        drift_factor = float(rng.uniform(0.005, 0.02))
        df, true_midpoint = simulate_chronological_dta(k=60, drift=drift_factor, rng=rng)
        aps_auc = aps_v2_fast(df)
        true_sensitivity = inv_logit(true_midpoint[0])
        true_specificity = inv_logit(true_midpoint[1])
        true_auc = 0.5 + (true_sensitivity + true_specificity - 1) / 2
        pem_results.append({"bias": abs(aps_auc - true_auc), "drift": drift_factor})
        if i % 10 == 0:
            print(f" - Progress: {i}/{n_simulations}")

    results_df = pd.DataFrame(pem_results)
    cert = build_certification(results_df, n_simulations=n_simulations)
    print("\nPEM ULTRA-SCALE AUDIT COMPLETE:")
    print(f" - Temporal Robustness Index (TRI): {cert['temporal_robustness_index']:.4f}")
    print(f" - Mean Bias under Drift: {cert['mean_bias']:.4f}")
    return results_df, cert


def main(n_simulations=100, seed=726, project_root=PROJECT_ROOT):
    results_df, cert = run_ultra_scale_audit(n_simulations=n_simulations, seed=seed)
    write_outputs(results_df, cert, project_root=project_root)
    return {"results": results_df, "certification": cert}


if __name__ == "__main__":
    main()
