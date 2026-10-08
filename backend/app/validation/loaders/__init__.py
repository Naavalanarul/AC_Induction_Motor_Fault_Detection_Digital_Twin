"""Dataset loaders. Each returns a list of `Record` (see app/validation/records.py)."""

from __future__ import annotations

from pathlib import Path

from app.validation.loaders.base import DatasetInfo, DatasetLoader, DatasetUnavailable, LoaderOptions
from app.validation.loaders.bruinsma import BruinsmaLoader
from app.validation.loaders.estogu import EstoguLoader
from app.validation.loaders.liman_c import LimanCLoader
from app.validation.loaders.usp_brb import UspBrbLoader

LOADERS: dict[str, type[DatasetLoader]] = {
    "bruinsma": BruinsmaLoader,
    "liman_c": LimanCLoader,
    "estogu": EstoguLoader,
    "usp_brb": UspBrbLoader,
}


def get_loader(name: str, root: Path | str, options: LoaderOptions | None = None) -> DatasetLoader:
    if name not in LOADERS:
        raise DatasetUnavailable(f"unknown dataset {name!r}; choose one of {sorted(LOADERS)}")
    return LOADERS[name](root, options)


__all__ = ["LOADERS", "DatasetInfo", "DatasetLoader", "DatasetUnavailable", "LoaderOptions", "get_loader"]
