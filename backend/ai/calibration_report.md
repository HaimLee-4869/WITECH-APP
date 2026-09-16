# Hand-only deployment calibration report

Thresholds were selected on known-user cross-session validation only.
Unseen-user results are post-selection analysis.

## Global operating points (3 enrollment takes per gesture)

| Point | Threshold | Validation FAR | Validation FRR | Unseen FAR | Unseen FRR | Unseen accuracy |
|---|---:|---:|---:|---:|---:|---:|
| EER | 0.436046 | 2.86% | 2.86% | 12.50% | 28.72% | 82.74% |
| FAR≤5% | 0.272128 | 5.00% | 2.14% | 20.51% | 18.58% | 80.06% |
| FAR≤1% | 0.627516 | 0.95% | 4.29% | 7.16% | 40.54% | 83.04% |

## Enrollment sweep (global validation-EER threshold)

| Takes/gesture | Validation EER | Unseen accuracy | Unseen FAR | Unseen FRR |
|---:|---:|---:|---:|---:|
| 1 | 2.86% | 73.31% | 19.38% | 44.26% |
| 3 | 2.86% | 82.74% | 12.50% | 28.72% |
| 4 | 2.86% | 82.84% | 13.62% | 25.68% |

## Threshold scheme comparison (3 takes)

| Scheme | Validation accuracy | Validation FAR | Validation FRR | Unseen accuracy | Unseen FAR | Unseen FRR |
|---|---:|---:|---:|---:|---:|---:|
| Global | 97.14% | 2.86% | 2.86% | 82.74% | 12.50% | 28.72% |
| Gesture-specific | 96.84% | 3.21% | 2.86% | 81.94% | 15.59% | 23.99% |
