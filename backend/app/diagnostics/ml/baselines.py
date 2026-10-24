"""diagnostics/ml/baselines.py — Deep neural network baselines for sequence features.

Provides comparable neural network architectures operating on the identical input tensor
shape (batch, seq_len, n_features) as ConvBiLSTM:
- 1D-CNN only (temporal convolutions over window sequences)
- BiLSTM only (recurrent sequence model without convolutional feature extractor)
- MLP (multi-layer perceptron over flattened window-feature sequence)
"""

from __future__ import annotations

import torch
from torch import nn


class CNN1D(nn.Module):
    """1D-CNN sequence baseline: Conv1d -> BatchNorm -> ReLU -> Conv1d -> AvgPool -> Linear."""

    def __init__(
        self,
        n_features: int,
        n_classes: int,
        conv1: int = 32,
        conv2: int = 64,
        dropout: float = 0.3,
    ):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(n_features, conv1, kernel_size=3, padding=1),
            nn.BatchNorm1d(conv1),
            nn.ReLU(),
            nn.Conv1d(conv1, conv2, kernel_size=3, padding=1),
            nn.BatchNorm1d(conv2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Linear(conv2, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, features) -> transpose to (batch, features, seq)
        h = self.conv(x.transpose(1, 2)).squeeze(-1)  # (batch, conv2)
        return self.head(h)


class BiLSTMOnly(nn.Module):
    """BiLSTM sequence baseline: 2-way recurrent encoding directly on raw feature sequence."""

    def __init__(
        self,
        n_features: int,
        n_classes: int,
        hidden: int = 64,
        dropout: float = 0.3,
    ):
        super().__init__()
        self.lstm = nn.LSTM(n_features, hidden, batch_first=True, bidirectional=True)
        self.drop = nn.Dropout(dropout)
        self.head = nn.Linear(2 * hidden, n_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, features)
        out, _ = self.lstm(x)
        return self.head(self.drop(out.mean(dim=1)))


class MLP(nn.Module):
    """Feedforward MLP baseline on flattened window-feature sequence."""

    def __init__(
        self,
        n_features: int,
        n_classes: int,
        seq_len: int = 5,
        hidden1: int = 128,
        hidden2: int = 64,
        dropout: float = 0.3,
    ):
        super().__init__()
        self.seq_len = seq_len
        self.net = nn.Sequential(
            nn.Linear(seq_len * n_features, hidden1),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden1, hidden2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden2, n_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq, features) -> flatten to (batch, seq * features)
        flat = x.reshape(x.size(0), -1)
        return self.net(flat)


def get_baseline_model(
    model_name: str,
    n_features: int,
    n_classes: int,
    seq_len: int = 5,
) -> nn.Module:
    """Model factory returning a model accepting (batch, seq_len, n_features)."""
    m = model_name.lower().replace("-", "_")
    if m in ("conv_bilstm", "convbilstm"):
        from app.diagnostics.ml.model import ConvBiLSTM

        return ConvBiLSTM(n_features, n_classes)
    elif m in ("cnn", "1d_cnn", "cnn1d", "1d-cnn"):
        return CNN1D(n_features, n_classes)
    elif m in ("bilstm", "bilstm_only", "lstm"):
        return BiLSTMOnly(n_features, n_classes)
    elif m in ("mlp", "feedforward", "dense"):
        return MLP(n_features, n_classes, seq_len=seq_len)
    else:
        raise ValueError(
            f"Unknown model name '{model_name}'. Choose from: conv_bilstm, 1d_cnn, bilstm, mlp."
        )


def count_parameters(model: nn.Module) -> int:
    """Return total number of trainable parameters in a PyTorch module."""
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
