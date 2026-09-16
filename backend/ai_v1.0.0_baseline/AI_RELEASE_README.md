# WITECH hand-only AI release

This folder is directly importable by the FastAPI server. It contains the
hand-only D=127 gesture classifier and two-stream SupCon authentication encoder.

## Versions

- Authentication: `handonly-supcon-v1.0.0`
- Gesture: `handonly-gesture-1dcnn-v1.0.0`
- Authentication embedding: 128-D, float32, L2-normalized
- Runtime: Python 3.9+; CPU supported

## Input contract

Each call accepts either a payload object or its `frames` list. Passing the
payload object is recommended because camera dimensions are required:

```python
payload = {
    "width": 1920,
    "height": 1080,
    "handedness": "Right",
    "frames": [
        {
            "tMs": 0.0,
            "landmarks": [{"x": 0.1, "y": 0.2, "z": -0.01}, ...]  # 21
        },
        ...
    ],
}
```

Requirements:

- At least 8 captured and 8 valid hand frames
- At least 750 ms between the first and last timestamp
- Strictly increasing `tMs`
- Camera `width` and `height`
- This version is trained with handedness-based canonicalization and therefore
  accepts **right-hand captures only**. The UI must instruct/enforce right hand;
  a hard-coded `Right` label must not be used to disguise actual left-hand input.

Sequences are internally interpolated/resampled to `[32,127]`. D=127 is hand
position 63 + real-time velocity 63 + detection mask 1. No pose landmarks are
used. The CNN sees position and velocity in separate branches and does not use
the detection mask as an identity feature.

## Server usage

```python
from ai_release.encoder import (
    MODEL_VERSION,
    GESTURE_MODEL_VERSION,
    load_model,
    embed,
    embed_batch,
    classify_gesture,
)

load_model()  # exactly once during FastAPI startup
vector = embed(payload)                 # (128,), normalized
vectors = embed_batch([payload, ...])   # (N,128), normalized
gesture_id, confidence = classify_gesture(payload)
```

The release serializes model forward calls with an internal re-entrant lock, so
concurrent FastAPI calls are safe. Use `embed_batch()` for reindexing throughput.

Cosine scoring, template averaging and threshold decisions intentionally remain
in the backend. Normalize the averaged template before its dot product with an
embedding. Store raw captures permanently and embeddings with `MODEL_VERSION`.

See `thresholds.json` for the selected global operating points and
`preprocess.json` for the exact training-time normalization configuration.

## Selected operating policy

- Threshold scheme: global
- Enrollment: one selected personal gesture x 3 takes (3 total)
- Default threshold: `0.627516` (known-user validation FAR <= 1%)
- Validation at that point: FAR 0.95%, FRR 4.29%
- Completely unseen-user analysis: FAR 7.16%, FRR 40.54%, accuracy 83.04%

The unseen-user FAR shows that this research model does not yet guarantee a 1%
FAR in deployment. It is suitable for the project demonstration, not as the
sole control for a safety-critical or real access-control system.

## CPU measurement

Measured on the development Apple-silicon Mac with PyTorch 2.8.0, including
raw-frame feature generation and model forward pass:

- `embed()`: mean 1.73 ms, p95 1.99 ms
- `classify_gesture()`: mean 1.62 ms, p95 1.80 ms
- `embed_batch()` with 16 captures: mean 25.48 ms total

Use `cpu_benchmark.json` for the machine details. Latency will vary by server.
