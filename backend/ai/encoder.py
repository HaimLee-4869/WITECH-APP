"""Stable import surface for WITECH FastAPI integration."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import numpy as np
import torch

try:
    from .features import build_hand_features
    from .model_defs import GestureEmbedding1DCNN, HandOnlySupCon1DCNN
except ImportError:  # Allows ``import encoder`` when ai_release is on sys.path.
    from features import build_hand_features
    from model_defs import GestureEmbedding1DCNN, HandOnlySupCon1DCNN


MODEL_VERSION = "handonly-supcon-v1.0.0"
GESTURE_MODEL_VERSION = "handonly-gesture-1dcnn-v1.0.0"
EMBEDDING_DIM = 128

_ROOT = Path(__file__).resolve().parent
_AUTH_PATH = _ROOT / "weights" / "auth_handonly_supcon_v1.pt"
_GESTURE_PATH = _ROOT / "weights" / "gesture_handonly_1dcnn_v1.pt"
_STATE_LOCK = threading.RLock()
_AUTH_MODEL = None
_GESTURE_MODEL = None
_AUTH_CKPT = None
_GESTURE_CKPT = None


def _construct_models(device: torch.device):
    auth_ckpt = torch.load(_AUTH_PATH, map_location=device, weights_only=False)
    gesture_ckpt = torch.load(_GESTURE_PATH, map_location=device, weights_only=False)
    if int(auth_ckpt["input_dim"]) != 127 or int(gesture_ckpt["input_dim"]) != 127:
        raise RuntimeError("release weights do not match the D=127 feature contract")

    auth_model = HandOnlySupCon1DCNN(
        input_dim=auth_ckpt["input_dim"],
        num_classes=auth_ckpt["num_classes"],
        embedding_dim=auth_ckpt["embedding_dim"],
    )
    gesture_model = GestureEmbedding1DCNN(
        input_dim=gesture_ckpt["input_dim"],
        num_classes=gesture_ckpt["num_classes"],
        embedding_dim=gesture_ckpt["embedding_dim"],
    )
    auth_model.load_state_dict(auth_ckpt["model_state_dict"])
    gesture_model.load_state_dict(gesture_ckpt["model_state_dict"])
    return auth_model.to(device).eval(), gesture_model.to(device).eval(), auth_ckpt, gesture_ckpt


def load_model(device: str = "cpu"):
    """Load both models once during server startup; repeated calls are harmless."""

    global _AUTH_MODEL, _GESTURE_MODEL, _AUTH_CKPT, _GESTURE_CKPT
    requested_device = torch.device(device)
    with _STATE_LOCK:
        if _AUTH_MODEL is None:
            _AUTH_MODEL, _GESTURE_MODEL, _AUTH_CKPT, _GESTURE_CKPT = _construct_models(
                requested_device
            )
    return {
        "model_version": MODEL_VERSION,
        "gesture_model_version": GESTURE_MODEL_VERSION,
        "device": str(next(_AUTH_MODEL.parameters()).device),
    }


def _ensure_loaded():
    if _AUTH_MODEL is None:
        load_model("cpu")


def _normalize(features: np.ndarray, duration: np.ndarray, checkpoint: dict):
    mean = np.asarray(checkpoint["sequence_mean"], dtype=np.float32)
    std = np.asarray(checkpoint["sequence_std"], dtype=np.float32)
    x = (features - mean) / std
    d = (duration - float(checkpoint["duration_mean"])) / float(checkpoint["duration_std"])
    return x.astype(np.float32), d.astype(np.float32)


def _prepare_one(frames: Any):
    features, duration = build_hand_features(frames, require_right_hand=True)
    return features, duration


def _auth_forward(features: np.ndarray, durations: np.ndarray) -> np.ndarray:
    _ensure_loaded()
    x, d = _normalize(features, durations, _AUTH_CKPT)
    with _STATE_LOCK, torch.inference_mode():
        embedding, _ = _AUTH_MODEL(torch.from_numpy(x), torch.from_numpy(d))
    output = embedding.cpu().numpy().astype(np.float32)
    output /= np.maximum(np.linalg.norm(output, axis=1, keepdims=True), 1e-12)
    return output


def embed(frames) -> np.ndarray:
    """Return one L2-normalized authentication embedding with shape ``[128]``."""

    features, duration = _prepare_one(frames)
    return _auth_forward(features[None, ...], np.asarray([duration], np.float32))[0]


def embed_batch(list_of_frames) -> np.ndarray:
    """Return L2-normalized embeddings with shape ``[N,128]``."""

    prepared = [_prepare_one(frames) for frames in list_of_frames]
    if not prepared:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)
    features = np.stack([item[0] for item in prepared])
    durations = np.asarray([item[1] for item in prepared], dtype=np.float32)
    return _auth_forward(features, durations)


def classify_gesture(frames) -> tuple[str, float]:
    """Return ``(gesture_id, softmax_confidence)`` for one capture."""

    _ensure_loaded()
    features, duration = _prepare_one(frames)
    x, d = _normalize(
        features[None, ...], np.asarray([duration], np.float32), _GESTURE_CKPT
    )
    with _STATE_LOCK, torch.inference_mode():
        _, logits = _GESTURE_MODEL(torch.from_numpy(x), torch.from_numpy(d))
        probabilities = torch.softmax(logits, dim=1)[0]
    index = int(probabilities.argmax().item())
    return str(_GESTURE_CKPT["classes"][index]), float(probabilities[index].item())


def release_metadata() -> dict:
    """Expose version and preprocessing information for health/config endpoints."""

    with (_ROOT / "preprocess.json").open(encoding="utf-8") as handle:
        return json.load(handle)
