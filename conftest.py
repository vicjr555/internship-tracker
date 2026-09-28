import pytest


@pytest.fixture(autouse=True)
def simple_static_storage(settings):
    """Tests don't run collectstatic, so use plain static storage instead of the
    production manifest storage (which errors on files missing from its manifest)."""
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
