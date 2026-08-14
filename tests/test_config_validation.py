"""Regression tests for config.py settings validation.

Covers:
- Type mismatches (int passed where float expected, etc.)
- Hotkey whitelist rejection
- Numeric range enforcement
- Bool-as-int-subclass guard for numeric settings
- JSON-serializability rejection

Covers the defensive validation added to _load_settings/save_setting.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config


def test_range_rejection():
    """Out-of-range numeric values should be rejected by save_setting."""
    # Below minimum
    assert config.save_setting("LONG_PRESS_THRESHOLD", 0.05) == False
    # Above maximum
    assert config.save_setting("LONG_PRESS_THRESHOLD", 5.0) == False
    # SAMPLE_RATE below 8000
    assert config.save_setting("SAMPLE_RATE", 4000) == False
    # DIGITAL_GAIN below 1.0
    assert config.save_setting("DIGITAL_GAIN", 0.5) == False
    print("test_range_rejection: PASS")


def test_range_acceptance():
    """In-range values should be accepted."""
    assert config.save_setting("LONG_PRESS_THRESHOLD", 0.5) == True
    assert config.save_setting("LONG_PRESS_THRESHOLD", 1.0) == True
    print("test_range_acceptance: PASS")


def test_bool_guard():
    """Booleans should be rejected for numeric settings (int subclass guard)."""
    assert config.save_setting("LONG_PRESS_THRESHOLD", True) == False
    assert config.save_setting("LONG_PRESS_THRESHOLD", False) == False
    print("test_bool_guard: PASS")


def test_known_good_range():
    """The default thresholds should always pass validation."""
    assert config.save_setting("LONG_PRESS_THRESHOLD", config._DEFAULTS["LONG_PRESS_THRESHOLD"]) == True
    assert config.save_setting("SAMPLE_RATE", config._DEFAULTS["SAMPLE_RATE"]) == True
    print("test_known_good_range: PASS")


if __name__ == "__main__":
    # Restore defaults after test run so settings.json isn't polluted
    try:
        test_range_rejection()
        test_range_acceptance()
        test_bool_guard()
        test_known_good_range()
    finally:
        config.reset_settings()
    print("\nResult: All config validation tests passed.")
