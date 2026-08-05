"""Runtime resource limits shared by local embedding and reranking models."""
from __future__ import annotations

import logging
import os

_configured_threads: int | None = None


def configure_local_cpu(threads: int) -> None:
    """Limit local ML libraries to a small, predictable CPU thread count.

    Container CPU shares alone are only a scheduling weight in the installed
    Airflow Docker provider.  Explicit Torch/BLAS/tokenizer limits keep the
    model from eagerly using every host core even when the machine is idle.
    """

    global _configured_threads
    if _configured_threads == threads:
        return

    thread_value = str(threads)
    for name in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "RAYON_NUM_THREADS",
    ):
        os.environ[name] = thread_value
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    import torch

    torch.set_num_threads(threads)
    try:
        # PyTorch only allows this to be set before inter-op work starts.
        torch.set_num_interop_threads(1)
    except RuntimeError:
        logging.getLogger(__name__).debug(
            "PyTorch inter-op threads were already initialized"
        )
    _configured_threads = threads
