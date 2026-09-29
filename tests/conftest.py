"""Keep test locks and secrets independent from a running local workspace."""
import importlib
import pytest

@pytest.fixture(autouse=True)
def isolated_runtime_files(tmp_path, monkeypatch):
    for name in ('grantiq.app.config', 'grantiq.app.security', 'grantiq.app.routes.web',
                 'grantiq.app.routes.research', 'grantiq.app.services.scheduler', 'grantiq.ingestion'):
        module = importlib.import_module(name)
        if hasattr(module, 'DATA_DIR'):
            monkeypatch.setattr(module, 'DATA_DIR', tmp_path)
