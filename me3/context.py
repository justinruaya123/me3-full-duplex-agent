"""Operator-selected project context folder, using the normal files pipeline."""

from pathlib import Path

from me3.files import main

if __name__ == "__main__":
    main(default_source=Path("context"))
