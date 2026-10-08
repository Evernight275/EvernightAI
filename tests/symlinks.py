import os
import tempfile
from pathlib import Path

import pytest


def _symlinks_supported() -> bool:
    with tempfile.TemporaryDirectory() as directory:
        try:
            os.symlink(directory, Path(directory) / "link", target_is_directory=True)
        except OSError:
            return False
    return True


requires_symlinks = pytest.mark.skipif(
    not _symlinks_supported(),
    reason="Creating symlinks is not permitted here (enable Windows Developer Mode)",
)
