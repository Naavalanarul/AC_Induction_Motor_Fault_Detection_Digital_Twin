"""diagnostics/ml/model.py — Conv-BiLSTM classifier (PyTorch)."""

from __future__ import annotations

import torch
from torch import nn


class ConvBiLSTM(nn.Module):
    """Conv1d(32) -> Conv1d(64) over the window sequence -> BiLSTM(64) -> softmax classes."""

    def __init__(self, n_features: int, n_classes: int, conv1: int = 32, conv2: int = 64, hidden: int = 64,
                 dropout: float = 0.3):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(n_features, conv1, kernel_size=3, padding=1), nn.BatchNorm1d(conv1), nn.ReLU(),
            nn.Conv1d(conv1, conv2, kernel_size=3, padding=1), nn.BatchNorm1d(conv2), nn.ReLU(),
            nn.Dropout(dropout),
        )
        self.lstm = nn.LSTM(conv2, hidden, batch_first=True, bidirectional=True)
        self.head = nn.Linear(2 * hidden, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, features)
        h = self.conv(x.transpose(1, 2)).transpose(1, 2)
        out, _ = self.lstm(h)
        return self.head(out.mean(dim=1))  # logits; softmax applied at inference
