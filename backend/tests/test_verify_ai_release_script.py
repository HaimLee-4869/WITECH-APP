"""scripts/verify_ai_release.py가 현재 ai/ 모듈에서 전부 통과하는지."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_verify_ai_release_passes():
    out = subprocess.run(
        [sys.executable, "scripts/verify_ai_release.py"],
        cwd=BACKEND_DIR, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "FAIL 0건" in out.stdout
    assert out.stdout.count("[PASS]") >= 18
    assert "[WARN] 사유 코드" not in out.stdout      # 사유 코드 추정 불일치 없음
    assert "shared-dual-head" in out.stdout          # 교체된 실제 릴리스
    assert "manifest 무결성" in out.stdout            # 해시가 없으면 WARN으로라도 알린다
    assert "[PASS] duration = 촬영 길이" in out.stdout


def test_verify_ai_release_detects_broken_module(tmp_path):
    """user head norm이 1이 아닌 인코더를 넣으면 FAIL로 잡는다."""
    pkg = tmp_path / "brokenai"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "encoder.py").write_text(
        "from ai.encoder import *  # noqa\n"
        "from ai.encoder import embed as _embed\n"
        "def embed(payload):\n"
        "    gesture, user = _embed(payload)\n"
        "    return gesture, user * 2   # user L2 norm이 2가 된다\n",
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(tmp_path)}
    out = subprocess.run(
        [sys.executable, "scripts/verify_ai_release.py", "--encoder-module", "brokenai.encoder"],
        cwd=BACKEND_DIR, capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert out.returncode == 1, out.stdout + out.stderr
    assert "[FAIL] user head embed()[1]: (128,) float32, L2 norm=1" in out.stdout
