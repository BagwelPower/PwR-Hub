"""`python -m pwrhub` ile uygulamayı başlatır."""

import sys
from pathlib import Path

# Dosya doğrudan çalıştırıldığında da (Windows açılışındaki kısayol böyle yapar)
# `pwrhub` paketi bulunabilsin.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pwrhub.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
