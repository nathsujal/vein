# tests/test_config.py
from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from conftest import _write
from vein_core.config import (
    APP_ROOT,
    CONFIG_PATH_DEFAULT,
    DEFAULT,
    AppConfig,
    Daemon,
    Log,
    ensure_config,
    get_config,
    load_config,
    load_or_create,
    reload_config,
    write_config,
)
from vein_core.errors import ConfigValidationError, ConfigSchemaMismatch

# errors.py

class TestErrorHierarchy:
    def test_config_error_is_exception(self):
        assert issubclass(ConfigValidationError, Exception)

    def test_schema_mismatch_is_config_error(self):
        """ConfigSchemaMismatch must be catchable as ConfigValidationError."""
        assert issubclass(ConfigSchemaMismatch, ConfigValidationError)

    def test_schema_mismatch_caught_by_config_error_handler(self):
        with pytest.raises(ConfigValidationError):
            raise ConfigSchemaMismatch("version '99' not supported")

    def test_config_error_message_preserved(self):
        with pytest.raises(ConfigValidationError, match="something broke"):
            raise ConfigValidationError("something broke")


# schema.py — Daemon

class TestDaemonDefaults:
    def test_default_host(self):
        assert Daemon().host == "127.0.0.1"

    def test_default_port(self):
        assert Daemon().port == 8765

    def test_base_url_format(self):
        d = Daemon(host="0.0.0.0", port=9000)
        assert d.base_url == "http://0.0.0.0:9000"

    def test_base_url_default(self):
        assert Daemon().base_url == "http://127.0.0.1:8765"

    def test_frozen(self):
        d = Daemon()
        with pytest.raises(FrozenInstanceError):
            d.host = "evil"


class TestDaemonHostValidation:
    def test_valid_custom_host(self):
        d = Daemon(host="0.0.0.0", port=8080)
        assert d.host == "0.0.0.0"

    def test_host_empty_string(self):
        with pytest.raises(ConfigValidationError, match="non-empty"):
            Daemon(host="")

    def test_host_non_string_int(self):
        with pytest.raises(ConfigValidationError, match="daemon.host must be a string"):
            Daemon(host=12345)  # type: ignore[arg-type]

    def test_host_non_string_none(self):
        with pytest.raises(ConfigValidationError, match="daemon.host must be a string"):
            Daemon(host=None)  # type: ignore[arg-type]


class TestDaemonPortValidation:
    def test_port_lower_boundary(self):
        assert Daemon(port=1).port == 1

    def test_port_upper_boundary(self):
        assert Daemon(port=65535).port == 65535

    def test_port_zero_invalid(self):
        with pytest.raises(ConfigValidationError, match="1..65535"):
            Daemon(port=0)

    def test_port_negative_invalid(self):
        with pytest.raises(ConfigValidationError, match="1..65535"):
            Daemon(port=-1)

    def test_port_above_max_invalid(self):
        with pytest.raises(ConfigValidationError, match="1..65535"):
            Daemon(port=65536)

    def test_port_string_invalid(self):
        """String port must be caught, not raise TypeError."""
        with pytest.raises((ConfigValidationError, TypeError)):
            Daemon(port="8765")  # type: ignore[arg-type]

    def test_port_float_invalid(self):
        """Float port must be caught, not silently accepted."""
        with pytest.raises((ConfigValidationError, TypeError)):
            Daemon(port=8765.0)  # type: ignore[arg-type]


class TestDaemonMultipleErrors:
    def test_host_and_port_both_bad_reported_together(self):
        """Both errors must appear in one ConfigValidationError, not stop at the first."""
        with pytest.raises(ConfigValidationError) as exc_info:
            Daemon(host="", port=0)
        msg = str(exc_info.value)
        assert "host" in msg
        assert "port" in msg


# schema.py — Log

class TestLogDefaults:
    def test_default_level(self):
        assert Log().level == "INFO"

    def test_default_json_format(self):
        assert Log().json_format is False

    def test_default_dir(self):
        assert Log().dir == APP_ROOT / "logs"

    def test_default_max_bytes(self):
        assert Log().max_bytes == 10 * 1024 * 1024

    def test_default_backup_count(self):
        assert Log().backup_count == 5

    def test_frozen(self):
        with pytest.raises(FrozenInstanceError):
            Log().level = "DEBUG"


class TestLogLevelValidation:
    @pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    def test_all_valid_levels_uppercase(self, level):
        assert Log(level=level).level == level

    @pytest.mark.parametrize("level", ["debug", "info", "warning", "error", "critical"])
    def test_lowercase_levels_normalised_to_upper(self, level):
        assert Log(level=level).level == level.upper()

    @pytest.mark.parametrize("level", ["Debug", "Info", "Warning", "Error", "Critical"])
    def test_mixed_case_levels_normalised(self, level):
        assert Log(level=level).level == level.upper()

    def test_invalid_level_raises(self):
        with pytest.raises(ConfigValidationError, match="log.level"):
            Log(level="VERBOSE")

    def test_empty_level_raises(self):
        with pytest.raises(ConfigValidationError, match="log.level"):
            Log(level="")

    def test_non_string_level_raises(self):
        """int level must produce ConfigValidationError, not AttributeError."""
        with pytest.raises((ConfigValidationError, AttributeError)):
            Log(level=1)  # type: ignore[arg-type]


class TestLogJsonFormat:
    def test_json_format_true(self):
        assert Log(json_format=True).json_format is True

    def test_json_format_string_raises(self):
        with pytest.raises(ConfigValidationError, match="json_format"):
            Log(json_format="true")  # type: ignore[arg-type]

    def test_json_format_int_raises(self):
        with pytest.raises(ConfigValidationError, match="json_format"):
            Log(json_format=1)  # type: ignore[arg-type]


class TestLogMaxBytes:
    def test_max_bytes_boundary_one(self):
        assert Log(max_bytes=1).max_bytes == 1

    def test_max_bytes_zero_raises(self):
        with pytest.raises(ConfigValidationError, match="max_bytes"):
            Log(max_bytes=0)

    def test_max_bytes_negative_raises(self):
        with pytest.raises(ConfigValidationError, match="max_bytes"):
            Log(max_bytes=-1)

    def test_max_bytes_string_raises(self):
        with pytest.raises((ConfigValidationError, TypeError)):
            Log(max_bytes="large")  # type: ignore[arg-type]


class TestLogBackupCount:
    def test_backup_count_zero_valid(self):
        """Zero means no backups — should be allowed."""
        assert Log(backup_count=0).backup_count == 0

    def test_backup_count_negative_raises(self):
        with pytest.raises(ConfigValidationError, match="backup_count"):
            Log(backup_count=-1)

    def test_backup_count_string_raises(self):
        with pytest.raises((ConfigValidationError, TypeError)):
            Log(backup_count="five")  # type: ignore[arg-type]


class TestLogMultipleErrors:
    def test_multiple_errors_collected(self):
        """All invalid fields must appear in one ConfigValidationError message."""
        with pytest.raises(ConfigValidationError) as exc_info:
            Log(level="OOPS", json_format="yes", max_bytes=0, backup_count=-1)  # type: ignore[arg-type]
        msg = str(exc_info.value)
        assert "level" in msg
        assert "json_format" in msg
        assert "max_bytes" in msg
        assert "backup_count" in msg


class TestLogDir:
    def test_dir_is_path_object(self):
        assert isinstance(Log().dir, Path)

    def test_custom_dir(self):
        p = Path("/tmp/mylogs")
        assert Log(dir=p).dir == p


# schema.py — AppConfig

class TestAppConfig:
    def test_default_config_version(self):
        assert AppConfig().config_version == "1"

    def test_default_contains_daemon(self):
        assert isinstance(AppConfig().daemon, Daemon)

    def test_default_contains_log(self):
        assert isinstance(AppConfig().log, Log)

    def test_frozen(self):
        with pytest.raises(FrozenInstanceError):
            AppConfig().config_version = "2"

    def test_DEFAULT_singleton_is_appconfig(self):
        assert isinstance(DEFAULT, AppConfig)

    def test_DEFAULT_has_correct_version(self):
        assert DEFAULT.config_version == "1"


# loader.py — load_config

class TestLoadConfigMissingFile:
    def test_missing_path_returns_DEFAULT(self, tmp_path):
        result = load_config(tmp_path / "nonexistent.toml")
        assert result is DEFAULT

    def test_missing_path_returns_DEFAULT_identity(self, tmp_path):
        """Callers relying on identity check get the same object."""
        r1 = load_config(tmp_path / "a.toml")
        r2 = load_config(tmp_path / "b.toml")
        assert r1 is r2


class TestLoadConfigValidToml:
    def test_full_valid_config(self, tmp_path):
        p = tmp_path / "config.toml"
        _write(p, """
config_version = "1"
[daemon]
host = "0.0.0.0"
port = 9090
[log]
level = "DEBUG"
json_format = true
max_bytes = 1048576
backup_count = 3
""")
        cfg = load_config(p)
        assert cfg.daemon.host == "0.0.0.0"
        assert cfg.daemon.port == 9090
        assert cfg.log.level == "DEBUG"
        assert cfg.log.json_format is True
        assert cfg.log.max_bytes == 1_048_576
        assert cfg.log.backup_count == 3

    def test_only_daemon_section(self, tmp_path):
        p = tmp_path / "config.toml"
        _write(p, '[daemon]\nhost = "1.2.3.4"\nport = 1234\n')
        cfg = load_config(p)
        assert cfg.daemon.host == "1.2.3.4"
        assert cfg.log.level == DEFAULT.log.level  # log defaults preserved

    def test_only_log_section(self, tmp_path):
        p = tmp_path / "config.toml"
        _write(p, "[log]\nlevel = \"WARNING\"\n")
        cfg = load_config(p)
        assert cfg.log.level == "WARNING"
        assert cfg.daemon.host == DEFAULT.daemon.host  # daemon defaults preserved

    def test_empty_sections(self, tmp_path):
        p = tmp_path / "config.toml"
        _write(p, "[daemon]\n[log]\n")
        cfg = load_config(p)
        assert cfg == DEFAULT

    def test_config_version_missing_uses_default(self, tmp_path):
        """A file without config_version should still load using DEFAULT version."""
        p = tmp_path / "config.toml"
        _write(p, '[daemon]\nport = 8765\n')
        cfg = load_config(p)
        assert cfg.config_version == DEFAULT.config_version

    def test_log_level_lowercase_in_file_normalised(self, tmp_path):
        p = tmp_path / "config.toml"
        _write(p, '[log]\nlevel = "debug"\n')
        cfg = load_config(p)
        assert cfg.log.level == "DEBUG"

    def test_log_dir_string_becomes_path(self, tmp_path):
        p = tmp_path / "config.toml"
        _write(p, f'[log]\ndir = "/tmp/logs"\n')
        cfg = load_config(p)
        assert isinstance(cfg.log.dir, Path)
        assert cfg.log.dir == Path("/tmp/logs")

    def test_log_dir_tilde_expanded(self, tmp_path):
        p = tmp_path / "config.toml"
        _write(p, '[log]\ndir = "~/vein-logs"\n')
        cfg = load_config(p)
        assert "~" not in str(cfg.log.dir)
        assert cfg.log.dir == Path("~/vein-logs").expanduser()


class TestLoadConfigValidationErrors:
    def test_invalid_toml_syntax(self, tmp_path):
        p = tmp_path / "config.toml"
        _write(p, "this is not [ valid toml !!!")
        with pytest.raises(ConfigValidationError, match="Invalid TOML"):
            load_config(p)

    def test_unsupported_config_version(self, tmp_path):
        p = tmp_path / "config.toml"
        _write(p, 'config_version = "99"\n')
        with pytest.raises(ConfigSchemaMismatch, match="99"):
            load_config(p)

    def test_schema_mismatch_is_config_error(self, tmp_path):
        p = tmp_path / "config.toml"
        _write(p, 'config_version = "99"\n')
        with pytest.raises(ConfigValidationError):  # caught by base class
            load_config(p)

    def test_unreadable_file(self, tmp_path):
        p = tmp_path / "config.toml"
        _write(p, 'config_version = "1"\n')
        os.chmod(p, 0o000)
        try:
            with pytest.raises(ConfigValidationError, match="Failed to read"):
                load_config(p)
        finally:
            os.chmod(p, 0o644)

    def test_config_version_float_treated_as_string(self, tmp_path):
        """TOML integer version like config_version = 1 (no quotes) is coerced to str."""
        p = tmp_path / "config.toml"
        _write(p, 'config_version = 1\n')
        cfg = load_config(p)
        assert cfg.config_version == "1"


# loader.py — write_config

class TestWriteConfig:
    def test_writes_valid_toml(self, tmp_path):
        p = tmp_path / "out.toml"
        write_config(DEFAULT, p)
        raw = tomllib.loads(p.read_text("utf-8"))
        assert raw["config_version"] == "1"

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "a" / "b" / "c" / "config.toml"
        write_config(DEFAULT, p)
        assert p.exists()

    def test_round_trip_equality(self, tmp_path):
        p = tmp_path / "config.toml"
        original = AppConfig(
            daemon=Daemon(host="10.0.0.1", port=5000),
            log=Log(level="WARNING", json_format=True, backup_count=0),
        )
        write_config(original, p)
        loaded = load_config(p)
        assert loaded == original

    def test_overwrites_existing_file(self, tmp_path):
        p = tmp_path / "config.toml"
        write_config(DEFAULT, p)
        modified = AppConfig(daemon=Daemon(port=9999))
        write_config(modified, p)
        loaded = load_config(p)
        assert loaded.daemon.port == 9999

    def test_log_dir_stored_as_string_in_toml(self, tmp_path):
        p = tmp_path / "config.toml"
        write_config(DEFAULT, p)
        raw = tomllib.loads(p.read_text("utf-8"))
        assert isinstance(raw["log"]["dir"], str)

    def test_no_tmp_file_left_on_success(self, tmp_path):
        p = tmp_path / "config.toml"
        write_config(DEFAULT, p)
        assert not (tmp_path / "config.toml.tmp").exists()

    def test_unwritable_parent_raises_config_error(self, tmp_path):
        locked = tmp_path / "locked"
        locked.mkdir()
        os.chmod(locked, 0o555)
        try:
            with pytest.raises(ConfigValidationError):
                write_config(DEFAULT, locked / "sub" / "config.toml")
        finally:
            os.chmod(locked, 0o755)


# loader.py — ensure_config

class TestEnsureConfig:
    def test_creates_file_when_missing(self, tmp_path):
        p = tmp_path / "config.toml"
        result = ensure_config(p)
        assert result is True
        assert p.exists()

    def test_returns_false_when_file_exists(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("# existing", encoding="utf-8")
        result = ensure_config(p)
        assert result is False

    def test_does_not_overwrite_existing_file(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("# do not touch", encoding="utf-8")
        ensure_config(p)
        assert p.read_text() == "# do not touch"

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "a" / "b" / "config.toml"
        ensure_config(p)
        assert p.exists()

    def test_created_content_is_valid_toml(self, tmp_path):
        p = tmp_path / "config.toml"
        ensure_config(p)
        raw = tomllib.loads(p.read_text("utf-8"))
        assert "config_version" in raw

    def test_created_content_round_trips_to_DEFAULT(self, tmp_path):
        p = tmp_path / "config.toml"
        ensure_config(p)
        loaded = load_config(p)
        assert loaded == DEFAULT

    def test_concurrent_creation_returns_false(self, tmp_path):
        """Simulates the race: file appears between exists() and os.open()."""
        p = tmp_path / "config.toml"
        original_open = os.open

        def _racing_open(path, flags, mode=0o777, *args, **kwargs):
            # Create the file just before our atomic open — simulating a race.
            Path(path).write_text("# raced", encoding="utf-8")
            return original_open(path, flags, mode, *args, **kwargs)

        with patch("vein_core.config.loader.os.open", side_effect=_racing_open):
            result = ensure_config(p)
        assert result is False

    def test_unwritable_parent_raises_config_error(self, tmp_path):
        locked = tmp_path / "locked"
        locked.mkdir()
        os.chmod(locked, 0o555)
        try:
            with pytest.raises(ConfigValidationError):
                ensure_config(locked / "sub" / "config.toml")
        finally:
            os.chmod(locked, 0o755)


# loader.py — load_or_create

class TestLoadOrCreate:
    def test_creates_and_loads_when_missing(self, tmp_path):
        p = tmp_path / "config.toml"
        cfg = load_or_create(p)
        assert p.exists()
        assert cfg == DEFAULT

    def test_loads_existing_without_modification(self, tmp_path):
        p = tmp_path / "config.toml"
        _write(p, 'config_version = "1"\n[daemon]\nport = 4321\n')
        cfg = load_or_create(p)
        assert cfg.daemon.port == 4321


# __init__.py — get_config / reload_config

class TestGetConfig:
    def test_repeated_calls_return_same_object(self, tmp_path):
        p = tmp_path / "config.toml"
        with patch("vein_core.config.CONFIG_PATH_DEFAULT", p):
            with patch("vein_core.config.loader.CONFIG_PATH_DEFAULT", p):
                get_config.cache_clear()
                r1 = get_config()
                r2 = get_config()
                assert r1 is r2
                get_config.cache_clear()

    def test_reload_returns_fresh_object_after_file_change(self, tmp_path):
        p = tmp_path / "config.toml"
        _write(p, 'config_version = "1"\n')

        with patch("vein_core.config.CONFIG_PATH_DEFAULT", p):
            with patch("vein_core.config.loader.CONFIG_PATH_DEFAULT", p):
                get_config.cache_clear()

                first = get_config()

                # Now change the file on disk.
                _write(p, 'config_version = "1"\n[daemon]\nport = 7777\n')
                second = reload_config()

                assert second.daemon.port == 7777
                get_config.cache_clear()

    def test_reload_clears_cache(self, tmp_path):
        p = tmp_path / "config.toml"
        _write(p, 'config_version = "1"\n')
        with patch("vein_core.config.CONFIG_PATH_DEFAULT", p):
            with patch("vein_core.config.loader.CONFIG_PATH_DEFAULT", p):
                get_config.cache_clear()
                first = get_config()
                reload_config()
                second = get_config()
                # After reload the cache is fresh — may or may not be same object
                # but must be a valid AppConfig.
                assert isinstance(second, AppConfig)
                get_config.cache_clear()


# Integration — full write → ensure → load round-trip

class TestIntegration:
    def test_write_ensure_load_round_trip(self, tmp_path):
        p = tmp_path / "config.toml"
        cfg_written = AppConfig(
            daemon=Daemon(host="192.168.1.1", port=1234),
            log=Log(level="error", json_format=False, backup_count=2),
        )
        write_config(cfg_written, p)
        cfg_loaded = load_config(p)
        assert cfg_loaded.daemon.host == "192.168.1.1"
        assert cfg_loaded.daemon.port == 1234
        assert cfg_loaded.log.level == "ERROR"   # normalised on write+load
        assert cfg_loaded.log.backup_count == 2

    def test_ensure_then_load_or_create_idempotent(self, tmp_path):
        p = tmp_path / "config.toml"
        ensure_config(p)
        cfg1 = load_or_create(p)
        cfg2 = load_or_create(p)
        assert cfg1 == cfg2

    def test_default_paths_are_under_app_root(self):
        assert CONFIG_PATH_DEFAULT.parent == APP_ROOT

    def test_APP_ROOT_is_absolute(self):
        assert APP_ROOT.is_absolute()