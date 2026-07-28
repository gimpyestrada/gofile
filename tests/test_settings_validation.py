"""Tests for settings dialog validation rules."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from settings_dialog import HOSTS, SettingsDialog  # noqa: E402


def _values(**overrides):
    """Build a values dict with every host disabled, then apply overrides."""
    values = {host.enabled_key: False for host in HOSTS}
    values.update({field.key: "" for host in HOSTS for field in host.fields})
    values.update(overrides)
    return values


class ValidationTests(unittest.TestCase):
    """validate() is a plain function of the form values."""

    def setUp(self) -> None:
        # Bypass __init__ so the rules can be tested without building widgets.
        self.dialog = SettingsDialog.__new__(SettingsDialog)

    def test_requires_at_least_one_host(self) -> None:
        error = self.dialog.validate(_values())
        self.assertIn("at least one", error.lower())

    def test_enabled_host_requires_its_credentials(self) -> None:
        error = self.dialog.validate(_values(gofile_enabled=True))
        self.assertIn("Gofile", error)
        self.assertIn("API token", error)

    def test_partially_filled_host_is_rejected(self) -> None:
        error = self.dialog.validate(
            _values(gofile_enabled=True, api_token="t")
        )
        self.assertIn("Account ID", error)

    def test_fully_configured_host_passes(self) -> None:
        self.assertIsNone(self.dialog.validate(
            _values(gofile_enabled=True, api_token="t", account_id="a")
        ))

    def test_disabled_host_credentials_are_not_required(self) -> None:
        """An unused host should not block saving just because it is blank."""
        self.assertIsNone(self.dialog.validate(
            _values(gofile_enabled=True, api_token="t", account_id="a",
                    apkadmin_enabled=False)
        ))

    def test_apkadmin_requires_all_three_values(self) -> None:
        error = self.dialog.validate(_values(
            apkadmin_enabled=True,
            apkadmin_cf_clearance="cf",
        ))
        self.assertIn("xfss", error)
        self.assertIn("User-Agent", error)

    def test_every_host_can_be_validated(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host.name):
                filled = _values(**{host.enabled_key: True})
                for field in host.fields:
                    filled[field.key] = "value"
                self.assertIsNone(self.dialog.validate(filled))


if __name__ == "__main__":
    unittest.main()
