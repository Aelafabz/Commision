"""Backward-compatible entry point — delegates to scripts/secondary_name_matcher.py."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

from secondary_name_matcher import (  # noqa: F401
    grafter,
    load_mismatched_data,
    main,
    name_comparator,
    run_secondary_matching,
)

if __name__ == "__main__":
    raise SystemExit(main())
