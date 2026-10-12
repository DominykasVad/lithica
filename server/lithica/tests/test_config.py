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


@pytest.mark.parametrize("domain", ["", None])
def test_refuses_smtp_without_domain(config_injector, domain):
    config_injector({"domain": domain, "smtp": {"host": "mail.example.com"}})
    with pytest.raises(errors.ConfigError, match="'domain' is not set"):
        config.validate_mail_domain()


def test_refuses_smtp_without_domain_key(config_injector):
    config_injector({"smtp": {"host": "mail.example.com"}})
    with pytest.raises(errors.ConfigError, match="'domain' is not set"):
        config.validate_mail_domain()


def test_accepts_smtp_with_domain(config_injector):
    config_injector(
        {"domain": "https://booru.example.com", "smtp": {"host": "mail.example.com"}}
    )
    config.validate_mail_domain()


@pytest.mark.parametrize("domain", ["", None, "https://booru.example.com"])
def test_domain_is_optional_without_smtp(config_injector, domain):
    config_injector({"domain": domain, "smtp": {"host": None}})
    config.validate_mail_domain()


def test_shipped_config_passes_the_mail_domain_check(config_injector):
    config_injector(config._file_config("config.yaml.dist"))
    config.validate_mail_domain()


@pytest.fixture
def valid_config(config_injector, tmpdir):
    content = config._file_config("config.yaml.dist")
    content.update(
        {
            "secret": "5c6f0b6d1d5a4d0f9a2b",
            "data_dir": str(tmpdir),
            "data_url": "data/",
            "database": "postgresql://user:pass@host/db",
            "debug": 0,
            "show_sql": 0,
        }
    )
    config_injector(content)
    return content


def test_shipped_settings_with_a_secret_are_valid(valid_config):
    config.validate()


@pytest.mark.parametrize(
    "change,message",
    [
        ({"secret": "change"}, "default value"),
        ({"default_rank": "emperor"}, "Default rank 'emperor'"),
        ({"data_dir": ""}, "'data_dir' is missing"),
        ({"data_dir": "relative/path"}, "must be an absolute path"),
        ({"data_url": ""}, "'data_url' is missing"),
        ({"database": ""}, "Database is not configured"),
        ({"webhooks": "http://example.com"}, "list of URLs"),
        ({"cors_origins": "https://example.com"}, "must be a list of origins"),
        ({"cors_origins": ["*"]}, "does not accept"),
        ({"cors_origins": ["https://example.com/"]}, "is not an origin"),
        ({"cors_origins": ["example.com"]}, "is not an origin"),
        ({"max_upload_size": 0}, "positive number of bytes"),
        ({"max_upload_size": "1G"}, "positive number of bytes"),
        ({"max_upload_size": 25.0e6}, "positive number of bytes"),
        ({"password_reset_token_lifetime": 0}, "positive number of seconds"),
        ({"password_reset_token_lifetime": "3600"}, "positive number of seconds"),
        ({"password_reset_token_lifetime": True}, "positive number of seconds"),
    ],
)
def test_refuses_invalid_settings(valid_config, change, message):
    valid_config.update(change)
    with pytest.raises(errors.ConfigError, match=message):
        config.validate()


def test_refuses_unknown_rank_in_privileges(valid_config):
    valid_config["privileges"]["posts:list"] = "emperor"
    with pytest.raises(errors.ConfigError, match="'posts:list' is missing"):
        config.validate()


@pytest.mark.parametrize(
    "smtp,message",
    [
        ({"port": None}, "port is not set"),
        ({"user": None}, "username is not set"),
        ({"pass": None}, "password is not set"),
        ({"from": None}, "From address must be set"),
    ],
)
def test_refuses_incomplete_smtp_settings(valid_config, smtp, message):
    valid_config["domain"] = "https://booru.example.com"
    valid_config["smtp"] = {
        "host": "mail.example.com",
        "port": 25,
        "user": "u",
        "pass": "p",
        "from": "booru@example.com",
        **smtp,
    }
    with pytest.raises(errors.ConfigError, match=message):
        config.validate()


def test_accepts_complete_smtp_settings(valid_config):
    valid_config["domain"] = "https://booru.example.com"
    valid_config["smtp"] = {
        "host": "mail.example.com",
        "port": 25,
        "user": "u",
        "pass": "p",
        "from": "booru@example.com",
    }
    config.validate()


def test_refuses_smtp_without_domain_at_startup(valid_config):
    valid_config["domain"] = None
    valid_config["smtp"]["host"] = "mail.example.com"
    with pytest.raises(errors.ConfigError, match="'domain' is not set"):
        config.validate()


@pytest.fixture
def read_config(monkeypatch):
    """Reads the configuration as at startup, from files that say `settings`."""

    def read(settings):
        monkeypatch.setattr(config, "_file_config", lambda _filename: dict(settings))
        monkeypatch.setattr(config, "_running_inside_container", lambda: False)
        return config._read_config()

    return read


def test_modules_come_from_the_files_without_the_variable(monkeypatch, read_config):
    monkeypatch.delenv("MODULES", raising=False)
    assert "modules" not in config._environment_overrides()
    assert read_config({"modules": ["from_file"]})["modules"] == ["from_file"]


def test_modules_variable_replaces_what_the_files_say(monkeypatch, read_config):
    monkeypatch.setenv("MODULES", "alpha,beta")
    assert read_config({"modules": ["from_file"]})["modules"] == ["alpha", "beta"]
    # replaced, not added to, and also when the files do not have the setting
    assert read_config({})["modules"] == ["alpha", "beta"]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("alpha", ["alpha"]),
        ("beta,alpha", ["beta", "alpha"]),
        (" alpha ,\tbeta\n", ["alpha", "beta"]),
        ("alpha,,beta,", ["alpha", "beta"]),
        (", ,alpha", ["alpha"]),
        ("", []),
        ("  ", []),
        (",", []),
    ],
)
def test_modules_variable_ignores_whitespace_and_empty_entries(
    monkeypatch, read_config, value, expected
):
    monkeypatch.setenv("MODULES", value)
    assert config._environment_overrides()["modules"] == expected
    assert read_config({"modules": ["from_file"]})["modules"] == expected
