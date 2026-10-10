import pytest

from lithica import config, errors


def test_default_secret_is_the_one_from_the_dist_file():
    assert config.default_secret() == "change"


def test_accepts_custom_secret(config_injector):
    config_injector({"secret": "5c6f0b6d1d5a4d0f9a2b"})
    config.validate_secret()


@pytest.mark.parametrize("secret", ["", "   ", None, 12345])
def test_refuses_missing_secret(config_injector, secret):
    config_injector({"secret": secret})
    with pytest.raises(errors.ConfigError, match="is not set"):
        config.validate_secret()


def test_refuses_absent_secret_key(config_injector):
    config_injector({})
    with pytest.raises(errors.ConfigError, match="is not set"):
        config.validate_secret()


def test_refuses_default_secret(config_injector):
    config_injector({"secret": config.default_secret()})
    with pytest.raises(errors.ConfigError, match="default value"):
        config.validate_secret()
