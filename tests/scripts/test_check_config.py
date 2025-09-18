"""Test check_config script."""

import json
import logging
import os
from unittest.mock import patch

import pytest

from homeassistant.config import YAML_CONFIG_FILE
from homeassistant.scripts import check_config

from tests.common import get_test_config_dir

BASE_CONFIG = (
    "homeassistant:\n"
    "  name: Home\n"
    "  latitude: -26.107361\n"
    "  longitude: 28.054500\n"
    "  elevation: 1600\n"
    "  unit_system: metric\n"
    "  time_zone: GMT\n"
    "\n\n"
)

BAD_CORE_CONFIG = "homeassistant:\n  unit_system: bad\n\n\n"


@pytest.fixture(autouse=True)
def reset_log_level():
    """Reset log level after each test case."""
    logger = logging.getLogger("homeassistant.loader")
    orig_level = logger.level
    yield
    logger.setLevel(orig_level)


@pytest.fixture(autouse=True)
async def apply_stop_hass(stop_hass: None) -> None:
    """Make sure all hass are stopped."""


@pytest.fixture
def mock_is_file():
    """Mock is_file."""
    # All files exist except for the old entity registry file
    with patch(
        "os.path.isfile", lambda path: not str(path).endswith("entity_registry.yaml")
    ):
        yield


def normalize_yaml_files(check_dict):
    """Remove configuration path from ['yaml_files']."""
    root = get_test_config_dir()
    return [key.replace(root, "...") for key in sorted(check_dict["yaml_files"].keys())]


@pytest.mark.parametrize("hass_config_yaml", [BAD_CORE_CONFIG])
@pytest.mark.usefixtures("mock_is_file", "mock_hass_config_yaml")
def test_bad_core_config() -> None:
    """Test a bad core config setup."""
    res = check_config.check(get_test_config_dir())
    assert res["except"].keys() == {"homeassistant"}
    assert res["except"]["homeassistant"][1] == {"unit_system": "bad"}
    assert res["warn"] == {}


@pytest.mark.parametrize("hass_config_yaml", [BASE_CONFIG + "light:\n  platform: demo"])
@pytest.mark.usefixtures("mock_is_file", "mock_hass_config_yaml")
def test_config_platform_valid() -> None:
    """Test a valid platform setup."""
    res = check_config.check(get_test_config_dir())
    assert res["components"].keys() == {"homeassistant", "light"}
    assert res["components"]["light"] == [{"platform": "demo"}]
    assert res["except"] == {}
    assert res["secret_cache"] == {}
    assert res["secrets"] == {}
    assert res["warn"] == {}
    assert len(res["yaml_files"]) == 1


@pytest.mark.parametrize(
    ("hass_config_yaml", "platforms", "error"),
    [
        (
            BASE_CONFIG + "beer:",
            {"homeassistant"},
            "Integration error: beer - Integration 'beer' not found.",
        ),
        (
            BASE_CONFIG + "light:\n  platform: beer",
            {"homeassistant", "light"},
            (
                "Platform error 'light' from integration 'beer' - "
                "Integration 'beer' not found."
            ),
        ),
    ],
)
@pytest.mark.usefixtures("mock_is_file", "mock_hass_config_yaml")
def test_component_platform_not_found(platforms: set[str], error: str) -> None:
    """Test errors if component or platform not found."""
    # Make sure they don't exist
    res = check_config.check(get_test_config_dir())
    assert res["components"].keys() == platforms
    assert res["except"] == {}
    assert res["secret_cache"] == {}
    assert res["secrets"] == {}
    assert res["warn"] == {check_config.WARNING_STR: [error]}
    assert len(res["yaml_files"]) == 1


@pytest.mark.parametrize(
    "hass_config_yaml_files",
    [
        {
            get_test_config_dir(YAML_CONFIG_FILE): BASE_CONFIG
            + "http:\n  cors_allowed_origins: !secret http_pw",
            get_test_config_dir(
                "secrets.yaml"
            ): "logger: debug\nhttp_pw: http://google.com",
        }
    ],
)
@pytest.mark.usefixtures("mock_is_file", "mock_hass_config_yaml")
def test_secrets() -> None:
    """Test secrets config checking method."""
    res = check_config.check(get_test_config_dir(), True)

    assert res["except"] == {}
    assert res["components"].keys() == {"homeassistant", "http"}
    assert res["components"]["http"] == {
        "cors_allowed_origins": ["http://google.com"],
        "ip_ban_enabled": True,
        "login_attempts_threshold": -1,
        "server_port": 8123,
        "ssl_profile": "modern",
        "use_x_frame_options": True,
        "server_host": ["0.0.0.0", "::"],
    }
    assert res["secret_cache"] == {
        get_test_config_dir("secrets.yaml"): {"http_pw": "http://google.com"}
    }
    assert res["secrets"] == {"http_pw": "http://google.com"}
    assert res["warn"] == {}
    assert normalize_yaml_files(res) == [
        ".../configuration.yaml",
        ".../secrets.yaml",
    ]


@pytest.mark.parametrize(
    "hass_config_yaml", [BASE_CONFIG + '  packages:\n    p1:\n      group: ["a"]']
)
@pytest.mark.usefixtures("mock_is_file", "mock_hass_config_yaml")
def test_package_invalid() -> None:
    """Test an invalid package."""
    res = check_config.check(get_test_config_dir())

    assert res["except"] == {}
    assert res["components"].keys() == {"homeassistant"}
    assert res["secret_cache"] == {}
    assert res["secrets"] == {}
    assert res["warn"].keys() == {"homeassistant.packages.p1.group"}
    assert res["warn"]["homeassistant.packages.p1.group"][1] == {"group": ["a"]}
    assert len(res["yaml_files"]) == 1


@pytest.mark.parametrize(
    "hass_config_yaml", [BASE_CONFIG + "automation: !include no.yaml"]
)
@pytest.mark.usefixtures("mock_hass_config_yaml")
def test_bootstrap_error() -> None:
    """Test a valid platform setup."""
    res = check_config.check(get_test_config_dir(YAML_CONFIG_FILE))
    err = res["except"].pop(check_config.ERROR_STR)
    assert len(err) == 1
    assert res["except"] == {}
    assert res["components"] == {}  # No components, load failed
    assert res["secret_cache"] == {}
    assert res["secrets"] == {}
    assert res["warn"] == {}
    assert res["yaml_files"] == {}


# New tests for JSON and fail-on-warnings functionality


@pytest.mark.parametrize("hass_config_yaml", [BASE_CONFIG])
@pytest.mark.usefixtures("mock_is_file", "mock_hass_config_yaml")
def test_run_backwards_compatibility_no_flags() -> None:
    """Test that run() with no flags maintains backwards compatibility."""
    # Test with valid config
    exit_code = check_config.run([])
    assert exit_code == 0

    # Test with config that has warnings
    with patch.object(check_config, "check") as mock_check:
        mock_check.return_value = {
            "except": {},
            "warn": {"light": ["warning message"]},
            "components": {"homeassistant": {}},
            "secrets": {},
            "secret_cache": {},
            "yaml_files": {},
        }
        # Without --fail-on-warnings, warnings should not affect exit code
        exit_code = check_config.run([])
        assert exit_code == 0

    # Test with config that has errors
    with patch.object(check_config, "check") as mock_check:
        mock_check.return_value = {
            "except": {"homeassistant": ["error message"]},
            "warn": {},
            "components": {"homeassistant": {}},
            "secrets": {},
            "secret_cache": {},
            "yaml_files": {},
        }
        exit_code = check_config.run([])
        assert exit_code == 1  # len(res["except"]) = 1 domain with errors


@pytest.mark.parametrize("hass_config_yaml", [BASE_CONFIG])
@pytest.mark.usefixtures("mock_is_file", "mock_hass_config_yaml")
def test_run_json_flag_only() -> None:
    """Test that --json flag works independently."""
    with (
        patch("builtins.print") as mock_print,
        patch.object(check_config, "check") as mock_check,
    ):
        mock_check.return_value = {
            "except": {"domain1": ["error1", "error2"]},
            "warn": {"domain2": ["warning1"]},
            "components": {"homeassistant": {}, "light": {}, "http": {}},
            "secrets": {},
            "secret_cache": {},
            "yaml_files": {},
        }

        exit_code = check_config.run(["--json"])

        # Should exit with code 1 (1 domain with errors)
        assert exit_code == 1

        # Should have printed JSON
        assert mock_print.call_count == 1
        json_output = mock_print.call_args[0][0]

        # Verify it's valid JSON
        parsed_json = json.loads(json_output)

        # Verify JSON structure
        assert "config_dir" in parsed_json
        assert "total_errors" in parsed_json
        assert "total_warnings" in parsed_json
        assert "errors" in parsed_json
        assert "warnings" in parsed_json
        assert "components" in parsed_json

        # Verify JSON content
        assert parsed_json["total_errors"] == 2  # 2 error messages
        assert parsed_json["total_warnings"] == 1  # 1 warning message
        assert parsed_json["errors"] == {"domain1": ["error1", "error2"]}
        assert parsed_json["warnings"] == {"domain2": ["warning1"]}
        assert set(parsed_json["components"]) == {"homeassistant", "light", "http"}


@pytest.mark.parametrize("hass_config_yaml", [BASE_CONFIG])
@pytest.mark.usefixtures("mock_is_file", "mock_hass_config_yaml")
def test_run_fail_on_warnings_flag_only() -> None:
    """Test that --fail-on-warnings flag works independently."""
    # Test with warnings only
    with patch.object(check_config, "check") as mock_check:
        mock_check.return_value = {
            "except": {},
            "warn": {"light": ["warning message"]},
            "components": {"homeassistant": {}},
            "secrets": {},
            "secret_cache": {},
            "yaml_files": {},
        }

        exit_code = check_config.run(["--fail-on-warnings"])
        assert exit_code == 1  # Should exit non-zero due to warnings

    # Test with no warnings or errors
    with patch.object(check_config, "check") as mock_check:
        mock_check.return_value = {
            "except": {},
            "warn": {},
            "components": {"homeassistant": {}},
            "secrets": {},
            "secret_cache": {},
            "yaml_files": {},
        }

        exit_code = check_config.run(["--fail-on-warnings"])
        assert exit_code == 0  # Should exit zero when no warnings/errors

    # Test with both errors and warnings
    with patch.object(check_config, "check") as mock_check:
        mock_check.return_value = {
            "except": {"domain1": ["error"]},
            "warn": {"domain2": ["warning"]},
            "components": {"homeassistant": {}},
            "secrets": {},
            "secret_cache": {},
            "yaml_files": {},
        }

        exit_code = check_config.run(["--fail-on-warnings"])
        assert exit_code == 1  # max(1, 1) = 1


@pytest.mark.parametrize("hass_config_yaml", [BASE_CONFIG])
@pytest.mark.usefixtures("mock_is_file", "mock_hass_config_yaml")
def test_run_both_flags_combined() -> None:
    """Test that both flags work together correctly."""
    with (
        patch("builtins.print") as mock_print,
        patch.object(check_config, "check") as mock_check,
    ):
        # Test with warnings only
        mock_check.return_value = {
            "except": {},
            "warn": {"light": ["warning message"]},
            "components": {"homeassistant": {}, "light": {}},
            "secrets": {},
            "secret_cache": {},
            "yaml_files": {},
        }

        exit_code = check_config.run(["--json", "--fail-on-warnings"])

        # Should exit with code 1 due to --fail-on-warnings and warnings present
        assert exit_code == 1

        # Should have printed JSON
        assert mock_print.call_count == 1
        json_output = mock_print.call_args[0][0]
        parsed_json = json.loads(json_output)

        # Verify JSON content
        assert parsed_json["total_errors"] == 0
        assert parsed_json["total_warnings"] == 1
        assert parsed_json["warnings"] == {"light": ["warning message"]}


@pytest.mark.parametrize("hass_config_yaml", [BASE_CONFIG])
@pytest.mark.usefixtures("mock_is_file", "mock_hass_config_yaml")
def test_run_json_output_structure() -> None:
    """Test JSON output contains all required fields with correct types."""
    with (
        patch("builtins.print") as mock_print,
        patch.object(check_config, "check") as mock_check,
    ):
        mock_check.return_value = {
            "except": {"domain1": ["error1", {"config": "bad"}]},
            "warn": {"domain2": ["warning1", {"config": "deprecated"}]},
            "components": {"homeassistant": {}, "light": {}, "automation": {}},
            "secrets": {},
            "secret_cache": {},
            "yaml_files": {},
        }

        exit_code = check_config.run(["--json", "--config", "/test/path"])

        json_output = mock_print.call_args[0][0]
        parsed_json = json.loads(json_output)

        # Should exit with code 1 due to errors
        assert exit_code == 1

        # Test all required fields are present
        required_fields = [
            "config_dir",
            "total_errors",
            "total_warnings",
            "errors",
            "warnings",
            "components",
        ]
        for field in required_fields:
            assert field in parsed_json, f"Missing required field: {field}"

        # Test field types and values
        assert isinstance(parsed_json["config_dir"], str)
        assert isinstance(parsed_json["total_errors"], int)
        assert isinstance(parsed_json["total_warnings"], int)
        assert isinstance(parsed_json["errors"], dict)
        assert isinstance(parsed_json["warnings"], dict)
        assert isinstance(parsed_json["components"], list)

        # Test counts are correct
        assert parsed_json["total_errors"] == 2  # 2 items in domain1 list
        assert parsed_json["total_warnings"] == 2  # 2 items in domain2 list

        # Test components is a list of strings
        assert all(isinstance(comp, str) for comp in parsed_json["components"])
        assert set(parsed_json["components"]) == {
            "homeassistant",
            "light",
            "automation",
        }


def test_run_exit_code_logic() -> None:
    """Test exit code logic for all flag combinations."""
    test_cases = [
        # (errors, warnings, flags, expected_exit_code)
        ({}, {}, [], 0),  # No errors, no warnings, no flags
        ({}, {}, ["--json"], 0),  # No errors, no warnings, json only
        (
            {},
            {},
            ["--fail-on-warnings"],
            0,
        ),  # No errors, no warnings, fail-on-warnings only
        (
            {},
            {},
            ["--json", "--fail-on-warnings"],
            0,
        ),  # No errors, no warnings, both flags
        (
            {},
            {"domain": ["warning"]},
            [],
            0,
        ),  # Warnings only, no flags (backwards compatible)
        ({}, {"domain": ["warning"]}, ["--json"], 0),  # Warnings only, json only
        (
            {},
            {"domain": ["warning"]},
            ["--fail-on-warnings"],
            1,
        ),  # Warnings only, fail-on-warnings
        (
            {},
            {"domain": ["warning"]},
            ["--json", "--fail-on-warnings"],
            1,
        ),  # Warnings only, both flags
        ({"domain": ["error"]}, {}, [], 1),  # Errors only, no flags
        ({"domain": ["error"]}, {}, ["--json"], 1),  # Errors only, json only
        (
            {"domain": ["error"]},
            {},
            ["--fail-on-warnings"],
            1,
        ),  # Errors only, fail-on-warnings
        (
            {"domain": ["error"]},
            {},
            ["--json", "--fail-on-warnings"],
            1,
        ),  # Errors only, both flags
        ({"domain": ["error"]}, {"domain2": ["warning"]}, [], 1),  # Both, no flags
        (
            {"domain": ["error"]},
            {"domain2": ["warning"]},
            ["--json"],
            1,
        ),  # Both, json only
        (
            {"domain": ["error"]},
            {"domain2": ["warning"]},
            ["--fail-on-warnings"],
            1,
        ),  # Both, fail-on-warnings
        (
            {"domain": ["error"]},
            {"domain2": ["warning"]},
            ["--json", "--fail-on-warnings"],
            1,
        ),  # Both, both flags
        ({"d1": ["e1"], "d2": ["e2"]}, {}, [], 2),  # Multiple error domains, no flags
        (
            {"d1": ["e1"], "d2": ["e2"]},
            {"d3": ["w1"]},
            ["--fail-on-warnings"],
            2,
        ),  # Multiple errors + warnings
    ]

    for errors, warnings, flags, expected_exit in test_cases:
        with patch("builtins.print"), patch.object(check_config, "check") as mock_check:
            mock_check.return_value = {
                "except": errors,
                "warn": warnings,
                "components": {"homeassistant": {}},
                "secrets": {},
                "secret_cache": {},
                "yaml_files": {},
            }

            exit_code = check_config.run(flags)
            assert exit_code == expected_exit, (
                f"Failed for errors={errors}, warnings={warnings}, flags={flags}. "
                f"Expected {expected_exit}, got {exit_code}"
            )


@pytest.mark.parametrize("hass_config_yaml", [BASE_CONFIG])
@pytest.mark.usefixtures("mock_is_file", "mock_hass_config_yaml")
def test_run_json_no_human_readable_output() -> None:
    """Test that JSON mode doesn't include human-readable messages."""
    with (
        patch("builtins.print") as mock_print,
        patch.object(check_config, "check") as mock_check,
    ):
        mock_check.return_value = {
            "except": {},
            "warn": {},
            "components": {"homeassistant": {}},
            "secrets": {},
            "secret_cache": {},
            "yaml_files": {},
        }

        check_config.run(["--json"])

        # Should only print once (the JSON output)
        assert mock_print.call_count == 1

        # The output should be valid JSON
        json_output = mock_print.call_args[0][0]
        json.loads(json_output)  # Validate it's valid JSON

        # Should not contain human-readable messages like "Testing configuration at"
        assert "Testing configuration at" not in json_output


@pytest.mark.parametrize("hass_config_yaml", [BASE_CONFIG])
@pytest.mark.usefixtures("mock_is_file", "mock_hass_config_yaml")
def test_run_human_readable_still_works() -> None:
    """Test that human-readable output still works without JSON flag."""
    with (
        patch("builtins.print") as mock_print,
        patch.object(check_config, "check") as mock_check,
    ):
        mock_check.return_value = {
            "except": {},
            "warn": {},
            "components": {"homeassistant": {}},
            "secrets": {},
            "secret_cache": {},
            "yaml_files": {},
        }

        check_config.run([])

        # Should print the "Testing configuration at" message
        printed_outputs = [
            call[0][0] if call[0] else "" for call in mock_print.call_args_list
        ]
        testing_message_found = any(
            "Testing configuration at" in output for output in printed_outputs
        )
        assert testing_message_found, (
            "Human-readable 'Testing configuration at' message not found"
        )


def test_run_with_config_path() -> None:
    """Test that config path is correctly included in JSON output."""
    with (
        patch("builtins.print") as mock_print,
        patch.object(check_config, "check") as mock_check,
    ):
        mock_check.return_value = {
            "except": {},
            "warn": {},
            "components": {"homeassistant": {}},
            "secrets": {},
            "secret_cache": {},
            "yaml_files": {},
        }

        test_config_path = "/custom/config/path"
        check_config.run(["--json", "--config", test_config_path])

        json_output = mock_print.call_args[0][0]
        parsed_json = json.loads(json_output)

        # The config_dir should include the full path
        expected_path = os.path.join(os.getcwd(), test_config_path)
        assert parsed_json["config_dir"] == expected_path
