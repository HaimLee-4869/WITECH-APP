"""scripts/*.py가 challenge_response 패키지를 import할 수 있게 경로를 잡는다."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
