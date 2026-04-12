from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from autocruise.presentation.app import launch  # noqa: E402


if __name__ == "__main__":
    launch()

