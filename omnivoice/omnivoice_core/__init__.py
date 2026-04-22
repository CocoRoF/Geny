"""Vendored inference-only subset of k2-fsa/OmniVoice.

This package is a *snapshot* copy of the upstream `omnivoice` package,
restricted to the modules required for inference (models + utils).
Training, data, eval, scripts, and CLI modules are intentionally excluded.

Upstream: https://github.com/k2-fsa/OmniVoice
License : Apache-2.0
Sync    : see ``Geny/omnivoice/docs/upstream_sync.md``
"""

import warnings

warnings.filterwarnings("ignore", module="torchaudio")
warnings.filterwarnings(
    "ignore",
    category=SyntaxWarning,
    message="invalid escape sequence",
    module="pydub.utils",
)
warnings.filterwarnings(
    "ignore",
    category=FutureWarning,
    module="torch.distributed.algorithms.ddp_comm_hooks",
)

from omnivoice_core.models.omnivoice import (  # noqa: E402
    OmniVoice,
    OmniVoiceConfig,
    OmniVoiceGenerationConfig,
)

__all__ = ["OmniVoice", "OmniVoiceConfig", "OmniVoiceGenerationConfig"]
