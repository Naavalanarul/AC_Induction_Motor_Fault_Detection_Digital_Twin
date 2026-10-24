#!/usr/bin/env bash
# scripts/reproduce_paper.sh — Reproduce all research-paper evidence, figures, and tables.
# Usage:
#   ./scripts/reproduce_paper.sh          # Full reproduction across all seeds (3-5 seeds)
#   ./scripts/reproduce_paper.sh --fast   # Quick CI reproduction (1 seed, reduced steps)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Locate python in virtual environment or fallback
if [ -f "backend/.venv/bin/python3" ]; then
    PYTHON="backend/.venv/bin/python3"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    echo "ERROR: python3 not found." >&2
    exit 1
fi

FAST_MODE=false
for arg in "$@"; do
    if [ "$arg" = "--fast" ]; then
        FAST_MODE=true
    fi
done

echo "========================================================================"
echo " AC Induction Motor Digital Twin: Research Paper Reproduction Pipeline"
echo " Working directory: $ROOT_DIR"
echo " Python executable: $PYTHON ($($PYTHON --version))"
echo " Fast mode: $FAST_MODE"
echo "========================================================================"

# ----------------------------------------------------------------------
# 1. Environment Verification
# ----------------------------------------------------------------------
echo "[1/9] Verifying software environment and dependencies..."
$PYTHON -c "
import sys, torch, sklearn, scipy, numpy, matplotlib
print(f'  Python {sys.version.split()[0]}')
print(f'  PyTorch {torch.__version__}')
print(f'  scikit-learn {sklearn.__version__}')
print(f'  scipy {scipy.__version__}')
print(f'  numpy {numpy.__version__}')
print(f'  matplotlib {matplotlib.__version__}')
" || { echo "ERROR: Dependency check failed. See reports/paper/ENVIRONMENT.md"; exit 1; }

export PYTHONPATH="$ROOT_DIR/backend"

if [ "$FAST_MODE" = true ]; then
    SEEDS="0"
    P7_STEPS=200
    echo "Running in fast CI mode (seeds: $SEEDS, P7 steps: $P7_STEPS)..."
else
    SEEDS="0 1 2"
    P7_STEPS=1200
    echo "Running in full publication mode (seeds: $SEEDS, P7 steps: $P7_STEPS)..."
fi

# ----------------------------------------------------------------------
# 2. Phase P2: Model Comparison on Identical Disjoint Splits
# ----------------------------------------------------------------------
echo "[2/9] Running Phase P2: Multi-Model Benchmark (Conv-BiLSTM vs 6 Baselines)..."
if [ "$FAST_MODE" = true ]; then
    $PYTHON -m app.validation.model_comparison --seeds 0 --out reports/paper/model_comparison/hard --dataset hard
else
    $PYTHON -m app.validation.model_comparison --seeds 0 1 2 3 4 --out reports/paper/model_comparison/hard --dataset hard
fi

# ----------------------------------------------------------------------
# 3. Phase P3: Channel Fusion & Thermal Resistance Compensation
# ----------------------------------------------------------------------
echo "[3/9] Running Phase P3: Multi-Source Fusion & Thermal Compensation Study..."
$PYTHON -m app.validation.fusion_study --out reports/paper/fusion_study --seeds $SEEDS

# ----------------------------------------------------------------------
# 4. Phase P4: Robustness Sweeps across Noise, Load, Supply, Mismatch
# ----------------------------------------------------------------------
echo "[4/9] Running Phase P4: Robustness Sweeps (Noise, Load, Supply, Mismatch, Severity)..."
$PYTHON -m app.validation.robustness --out reports/paper/robustness --seeds $SEEDS

# ----------------------------------------------------------------------
# 5. Phase P5: Supervisory SADA Anti-Hunting Evaluation
# ----------------------------------------------------------------------
echo "[5/9] Running Phase P5: SADA Supervisory Layer Evaluation & Chatter Study..."
$PYTHON -m app.validation.sada_study --out reports/paper/sada --seeds $SEEDS

# ----------------------------------------------------------------------
# 6. Phase P6: Motor Health Index (MHI) & Prognosis Evaluation
# ----------------------------------------------------------------------
echo "[6/9] Running Phase P6: MHI Behavior, Step Drops, and Prognosis Accuracy..."
$PYTHON -m app.validation.mhi_study --out reports/paper/mhi --seeds $SEEDS

# ----------------------------------------------------------------------
# 7. Phase P7: Latency to Detection and Long-Run False Alarms
# ----------------------------------------------------------------------
echo "[7/9] Running Phase P7: Latency to Detection and Long-Run False-Alarm Study..."
$PYTHON -m app.validation.latency_study --out reports/paper/latency --steps $P7_STEPS --seeds $SEEDS

# ----------------------------------------------------------------------
# 8. Phase P1 Check: Physical Real-Data Benchmarks
# ----------------------------------------------------------------------
echo "[8/9] Checking for external real physical datasets in data/..."
HAS_REAL_DATA=false
for ds in bruinsma liman_c estogu usp_brb; do
    if [ -d "data/$ds" ] && [ "$(ls -A "data/$ds" 2>/dev/null)" ]; then
        echo "  Found physical dataset: data/$ds. Executing P1 real-data evaluation..."
        $PYTHON -m app.validation.run --dataset "$ds" --protocol all --data-root "data/$ds" --out "reports/paper/real_$ds"
        HAS_REAL_DATA=true
    fi
done

if [ "$HAS_REAL_DATA" = false ]; then
    echo "  Notice: No physical experimental datasets found under data/ (human download step)."
    echo "  See PAPER_BLOCKERS.md and reports/paper/DATA_ACQUISITION.md for acquisition instructions."
    echo "  Skipping real-data protocol gracefully; proceeding with simulator and physical model assets."
fi

# ----------------------------------------------------------------------
# 9. Phase P8: Paper Figure Suite & Artifact Verification
# ----------------------------------------------------------------------
echo "[9/9] Generating comprehensive publication figures and verifying manifest..."
$PYTHON -m app.validation.paper_figures --reports reports/paper --out reports/paper/figures

# Verify all required manifest files exist and are non-empty
MANIFEST_FILE="reports/paper/MANIFEST.md"
if [ -f "$MANIFEST_FILE" ]; then
    echo "Verifying files in $MANIFEST_FILE..."
    MISSING_COUNT=0
    while IFS= read -r line || [ -n "$line" ]; do
        # Extract file paths matching backticked paths or plain relative paths
        file_path=$(echo "$line" | grep -o '`[^`]*`' | tr -d '`' || true)
        if [ -n "$file_path" ] && [[ "$file_path" == reports/paper/* ]]; then
            if [ ! -s "$file_path" ]; then
                echo "  WARNING / MISSING: $file_path"
                MISSING_COUNT=$((MISSING_COUNT + 1))
            fi
        fi
    done < "$MANIFEST_FILE"
    if [ "$MISSING_COUNT" -gt 0 ]; then
        echo "ERROR: $MISSING_COUNT files in MANIFEST.md are missing or empty." >&2
        exit 1
    fi
    echo "  All manifest artifacts verified successfully."
fi

echo "========================================================================"
echo " SUCCESS: Research paper reproduction completed successfully."
echo " All metrics, LaTeX tables, and publication figures are in reports/paper/"
echo "========================================================================"
exit 0
