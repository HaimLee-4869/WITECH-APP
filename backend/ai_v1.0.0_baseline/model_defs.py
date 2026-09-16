"""Neural-network definitions used by the WITECH hand-only release."""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class GestureEmbedding1DCNN(nn.Module):
    """Basic gesture 1D-CNN that also exposes a normalized embedding."""

    def __init__(self, input_dim: int = 127, num_classes: int = 5, embedding_dim: int = 128):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv1d(input_dim, 64, kernel_size=5, padding=2),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Dropout(0.20),
            nn.Conv1d(64, 96, kernel_size=3, padding=1),
            nn.BatchNorm1d(96),
            nn.ReLU(),
            nn.Conv1d(96, 128, kernel_size=3, padding=2, dilation=2),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.Dropout(0.30),
            nn.AdaptiveAvgPool1d(1),
        )
        self.embedding_head = nn.Linear(129, embedding_dim)
        self.classifier = nn.Linear(embedding_dim, num_classes)

    def forward(self, x: torch.Tensor, duration: torch.Tensor):
        h = self.features(x.transpose(1, 2)).squeeze(-1)
        h = torch.cat([h, duration.unsqueeze(1)], dim=1)
        embedding = F.normalize(self.embedding_head(h), p=2, dim=1)
        return embedding, self.classifier(embedding)


class HandOnlySupCon1DCNN(nn.Module):
    """Position/velocity two-stream encoder tailored to D=127 hand features."""

    def __init__(self, input_dim: int = 127, num_classes: int = 7, embedding_dim: int = 128):
        super().__init__()
        if int(input_dim) != 127:
            raise ValueError(f"Hand-only model expects D=127, got {input_dim}")

        def branch(dropout: float):
            return nn.Sequential(
                nn.Conv1d(63, 48, kernel_size=5, padding=2, bias=False),
                nn.BatchNorm1d(48),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Conv1d(48, 64, kernel_size=3, padding=2, dilation=2, bias=False),
                nn.BatchNorm1d(64),
                nn.ReLU(),
            )

        self.position_branch = branch(0.15)
        self.velocity_branch = branch(0.20)
        self.embedding_head = nn.Sequential(
            nn.Linear(257, 192),
            nn.LayerNorm(192),
            nn.ReLU(),
            nn.Dropout(0.20),
            nn.Linear(192, embedding_dim),
        )
        self.classifier = nn.Linear(embedding_dim, num_classes)

    @staticmethod
    def statistics_pool(features: torch.Tensor) -> torch.Tensor:
        mean = features.mean(dim=2)
        variance = features.var(dim=2, unbiased=False)
        std = torch.sqrt(variance.clamp_min(1e-6))
        return torch.cat([mean, std], dim=1)

    def forward(self, x: torch.Tensor, duration: torch.Tensor):
        if x.ndim != 3 or x.shape[-1] != 127:
            raise ValueError(f"Expected [B,32,127], got {tuple(x.shape)}")
        position = x[:, :, :63].transpose(1, 2)
        velocity = x[:, :, 63:126].transpose(1, 2)
        position_stats = self.statistics_pool(self.position_branch(position))
        velocity_stats = self.statistics_pool(self.velocity_branch(velocity))
        fused = torch.cat([position_stats, velocity_stats, duration.unsqueeze(1)], dim=1)
        embedding = F.normalize(self.embedding_head(fused), p=2, dim=1)
        return embedding, self.classifier(embedding)
