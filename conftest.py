from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def simple_static_storage(settings):
    """Tests don't run collectstatic, so use plain static storage instead of the
    production manifest storage (which errors on files missing from its manifest)."""
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture(autouse=True)
def no_https_redirect(settings):
    """With DEBUG=False (as in CI), production settings redirect every plain-HTTP
    request to HTTPS. The test client speaks plain HTTP, so turn that off in tests."""
    settings.SECURE_SSL_REDIRECT = False


@pytest.fixture(autouse=True)
def block_network():
    """Fail loudly if any test makes a real HTTP request through `requests`.
    Tests that need HTTP mock `requests.get` themselves, which bypasses this."""
    def refuse(*args, **kwargs):
        raise RuntimeError("Real network access is not allowed in tests. Mock requests.get.")

    with mock.patch("requests.sessions.Session.request", side_effect=refuse):
        yield
