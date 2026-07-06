#!/usr/bin/env bash
# Fetch the real-data evaluation corpus (NOT committed to git — ~180 MB unpacked).
# Autocast (Zou et al. 2022): resolved Metaculus/GJOpen questions with crowd
# forecast trajectories and resolutions. License/citation: see the repo README
# at https://github.com/andyzoujm/autocast
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/real
if [ ! -f data/real/autocast/autocast_questions.json ]; then
  curl -fL -o data/real/autocast.tar.gz \
    https://people.eecs.berkeley.edu/~hendrycks/autocast.tar.gz
  tar xzf data/real/autocast.tar.gz -C data/real
fi
python3 - <<'EOF'
from research.realeval.dataset import load_autocast, select_mechanistic
qs = select_mechanistic(load_autocast())
print(f"real-eval corpus ready: {len(qs)} mechanistic resolved binary questions")
EOF
