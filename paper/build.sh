#!/usr/bin/env bash
# Builds main.pdf. Deliberately does NOT prepend conda's bin to PATH: doing
# so shadows the system python3 (which has pyyaml etc. installed, per
# environment/requirements.txt) with conda's bare base-env python3, which
# does not -- a real gotcha hit while first writing this script. Table
# generation always uses the system python3 explicitly; only the LaTeX
# engine lookup falls back into conda's tree.
set -euo pipefail
cd "$(dirname "$0")"

PY=/usr/bin/python3
command -v "$PY" >/dev/null 2>&1 || PY=python3

"$PY" tables/gen_table2.py > tables/table2_resources.tex
"$PY" tables/gen_table5.py > tables/table5_lut_scaling.tex
"$PY" tables/gen_table_ztest.py > tables/table_ztest.tex

TECTONIC=""
if command -v tectonic >/dev/null 2>&1; then
  TECTONIC=tectonic
elif [ -x "$HOME/miniconda3/bin/tectonic" ]; then
  TECTONIC="$HOME/miniconda3/bin/tectonic"
fi

if [ -n "$TECTONIC" ]; then
  "$TECTONIC" main.tex
elif command -v latexmk >/dev/null 2>&1; then
  latexmk -pdf -interaction=nonstopmode main.tex
else
  echo "Neither tectonic nor latexmk found. Install one:" >&2
  echo "  conda install -c conda-forge tectonic" >&2
  echo "  (or) apt-get install texlive-latex-extra texlive-science latexmk" >&2
  exit 1
fi

echo "Built paper/main.pdf"
