"""Tests for existing-device lookup, including the empty-serial fallback.

Regression: when a NetBox device already exists with the same name but no
serial, the sync must adopt it and fill in the serial instead of creating a
duplicate (or spawning a `{name}_{serial}` variant).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import main
from main import (
    KEEP_TAG_PREFIX,
    _device_serial_is_empty,
    find_existing_device,
    should_preserve_field,
)


def _nb_device(id_, name, serial=None, site_id=1, tags=None):
    """Build a fake pynetbox device record."""
    site = SimpleNamespace(id=site_id, name=f"site-{site_id}") if site_id is not None else None
    return SimpleNamespace(
        id=id_,
        name=name,
        serial=serial,
        site=site,
        tags=tags or [],
        save=MagicMock(),
    )


def _site(site_id=1):
    return SimpleNamespace(id=site_id, name=f"site-{site_id}")


# ---------------------------------------------------------------------------
#  _device_serial_is_empty
# ---------------------------------------------------------------------------

class TestDeviceSerialIsEmpty:
    def test_none_serial_is_empty(self):
        assert _device_serial_is_empty(_nb_device(1, "d", serial=None)) is True

    def test_empty_string_is_empty(self):
        assert _device_serial_is_empty(_nb_device(1, "d", serial="")) is True

    def test_whitespace_only_is_empty(self):
        assert _device_serial_is_empty(_nb_device(1, "d", serial="   ")) is True

    def test_non_empty_serial_is_not_empty(self):
        assert _device_serial_is_empty(_nb_device(1, "d", serial="ABC")) is False

    def test_none_device_is_empty(self):
        assert _device_serial_is_empty(None) is True


# ---------------------------------------------------------------------------
#  find_existing_device — primary serial lookup (unchanged Layer 1 behavior)
# ---------------------------------------------------------------------------

class TestFindExistingSerialLookup:
    """The serial-first global lookup must remain unchanged."""

    def test_returns_serial_match(self):
        target = _nb_device(1, "dev", serial="ABC")
        nb = MagicMock()
        nb.dcim.devices.filter.return_value = [target]
        result = find_existing_device(nb, "ABC", "dev", _site(1))
        assert result is target
        # First call must be the global serial lookup.
        assert nb.dcim.devices.filter.call_args_list[0].kwargs == {"serial": "ABC"}

    def test_serial_lookup_has_no_site_binding(self):
        nb = MagicMock()
        nb.dcim.devices.filter.return_value = []
        find_existing_device(nb, "ABC", "dev", _site(1))
        first_call = nb.dcim.devices.filter.call_args_list[0].kwargs
        assert "serial" in first_call
        assert "site_id" not in first_call and "site" not in first_call

    def test_multiple_serial_matches_logs_and_picks_first(self, caplog):
        first = _nb_device(1, "a", serial="DUP")
        second = _nb_device(2, "b", serial="DUP")
        nb = MagicMock()
        nb.dcim.devices.filter.return_value = [first, second]
        with caplog.at_level("WARNING"):
            result = find_existing_device(nb, "DUP", "a", _site(1))
        assert result is first

    def test_no_serial_no_fallback_when_name_missing(self):
        # If UniFi device has no serial AND no name, nothing to fall back on.
        nb = MagicMock()
        nb.dcim.devices.filter.return_value = []
        assert find_existing_device(nb, "", "", _site(1)) is None
        # No second filter call attempted.
        assert nb.dcim.devices.filter.call_count == 0


# ---------------------------------------------------------------------------
#  find_existing_device — name+site fallback for empty-serial records
# ---------------------------------------------------------------------------

class TestFindExistingNameFallback:
    """Recovery path: adopt a same-name device with empty serial."""

    def test_falls_back_to_name_when_existing_has_empty_serial(self):
        adopted = _nb_device(7, "IT-SW01", serial=None, site_id=1)
        nb = MagicMock()
        # First call = serial lookup (empty); second = name+site fallback.
        nb.dcim.devices.filter.side_effect = [[], [adopted]]
        result = find_existing_device(nb, "ABC123", "IT-SW01", _site(1))
        assert result is adopted
        assert nb.dcim.devices.filter.call_args_list[1].kwargs == {
            "name": "IT-SW01",
            "site_id": 1,
        }

    def test_skips_name_match_when_existing_has_different_serial(self):
        # Same name, but the existing record already has a different serial
        # that UniFi STILL reports (not a replacement). Must NOT adopt.
        other = _nb_device(7, "IT-SW01", serial="OTHER-SERIAL", site_id=1)
        nb = MagicMock()
        nb.dcim.devices.filter.side_effect = [[], [other]]
        with patch.object(main, "_all_unifi_serials_global", {"OTHER-SERIAL"}):
            result = find_existing_device(nb, "ABC123", "IT-SW01", _site(1))
        assert result is None

    def test_prefers_serial_match_over_name_fallback(self):
        serial_match = _nb_device(1, "renamed-here", serial="ABC")
        name_match = _nb_device(2, "IT-SW01", serial=None, site_id=1)
        nb = MagicMock()
        # Serial lookup returns a result; name fallback must never run.
        nb.dcim.devices.filter.side_effect = [[serial_match], [name_match]]
        result = find_existing_device(nb, "ABC", "IT-SW01", _site(1))
        assert result is serial_match
        assert nb.dcim.devices.filter.call_count == 1

    def test_no_fallback_when_target_serial_is_empty(self):
        # If the UniFi device itself has no serial, we must not adopt a random
        # same-name device (would be ambiguous).
        adopted = _nb_device(7, "IT-SW01", serial=None, site_id=1)
        nb = MagicMock()
        nb.dcim.devices.filter.side_effect = [[], [adopted]]
        result = find_existing_device(nb, "", "IT-SW01", _site(1))
        assert result is None
        # Only the (empty) serial filter was attempted — no name lookup.
        assert nb.dcim.devices.filter.call_count == 1

    def test_multiple_empty_serial_matches_picks_first(self, caplog):
        first = _nb_device(1, "IT-SW01", serial=None, site_id=1)
        second = _nb_device(2, "IT-SW01", serial="", site_id=1)
        nb = MagicMock()
        nb.dcim.devices.filter.side_effect = [[], [first, second]]
        with caplog.at_level("WARNING"):
            result = find_existing_device(nb, "ABC", "IT-SW01", _site(1))
        assert result is first

    def test_name_lookup_exception_returns_none(self):
        nb = MagicMock()
        nb.dcim.devices.filter.side_effect = [[], RuntimeError("boom")]
        result = find_existing_device(nb, "ABC", "IT-SW01", _site(1))
        assert result is None

    def test_no_fallback_when_site_has_no_id(self):
        nb = MagicMock()
        nb.dcim.devices.filter.return_value = []
        result = find_existing_device(nb, "ABC", "IT-SW01", SimpleNamespace(name="s"))
        assert result is None
        # Only the serial lookup — name fallback cannot run without site_id.
        assert nb.dcim.devices.filter.call_count == 1


# ---------------------------------------------------------------------------
#  should_preserve_field("serial") — tag-driven, env has no flag for serial
# ---------------------------------------------------------------------------

class TestSerialPreservationGate:
    def test_serial_preserved_by_unifi_keep_serial_tag(self):
        from types import SimpleNamespace
        dev = SimpleNamespace(
            tags=[SimpleNamespace(slug=f"{KEEP_TAG_PREFIX}serial", name="serial")],
        )
        assert should_preserve_field(dev, "serial") is True

    def test_serial_preserved_by_unifi_keep_all_tag(self):
        from types import SimpleNamespace
        dev = SimpleNamespace(
            tags=[SimpleNamespace(slug=f"{KEEP_TAG_PREFIX}all", name="all")],
        )
        assert should_preserve_field(dev, "serial") is True

    def test_serial_not_preserved_by_default(self):
        from types import SimpleNamespace
        dev = SimpleNamespace(tags=[])
        assert should_preserve_field(dev, "serial") is False


# ---------------------------------------------------------------------------
#  find_existing_device — Step 3: replacement fallback (stale serial)
# ---------------------------------------------------------------------------

class TestFindExistingReplacementFallback:
    """Physical-replacement scenario: same name + new serial, old serial no
    longer in UniFi. The existing record should be adopted for serial
    overwrite when policy=replace."""

    def test_adopts_same_name_record_when_old_serial_is_stale(self):
        other = _nb_device(7, "IT-SW01", serial="OLD-SERIAL", site_id=1)
        nb = MagicMock()
        nb.dcim.devices.filter.side_effect = [[], [other]]
        with patch.object(main, "_all_unifi_serials_global", set()):
            result = find_existing_device(nb, "NEW-SERIAL", "IT-SW01", _site(1))
        assert result is other

    def test_skips_when_old_serial_still_in_unifi(self):
        # Same name, different serial, but old serial is still reported by
        # UniFi (e.g. moved to another site) — must NOT adopt.
        other = _nb_device(7, "IT-SW01", serial="OLD-SERIAL", site_id=1)
        nb = MagicMock()
        nb.dcim.devices.filter.side_effect = [[], [other]]
        with patch.object(main, "_all_unifi_serials_global", {"OLD-SERIAL"}):
            result = find_existing_device(nb, "NEW-SERIAL", "IT-SW01", _site(1))
        assert result is None

    def test_skips_when_policy_is_new(self):
        other = _nb_device(7, "IT-SW01", serial="OLD-SERIAL", site_id=1)
        nb = MagicMock()
        nb.dcim.devices.filter.side_effect = [[], [other]]
        with patch.object(main, "_all_unifi_serials_global", set()), \
             patch("main.load_name_conflict_policy", return_value=main.NAME_CONFLICT_NEW):
            result = find_existing_device(nb, "NEW-SERIAL", "IT-SW01", _site(1))
        assert result is None

    def test_skips_when_multiple_stale_candidates(self):
        a = _nb_device(8, "IT-SW01", serial="OLD-A", site_id=1)
        b = _nb_device(9, "IT-SW01", serial="OLD-B", site_id=1)
        nb = MagicMock()
        nb.dcim.devices.filter.side_effect = [[], [a, b]]
        with patch.object(main, "_all_unifi_serials_global", set()):
            result = find_existing_device(nb, "NEW", "IT-SW01", _site(1))
        assert result is None  # ambiguous — refuse

    def test_step2_empty_serial_takes_precedence_over_step3(self):
        """Empty-serial record is preferred over stale-serial record."""
        empty = _nb_device(10, "IT-SW01", serial=None, site_id=1)
        stale = _nb_device(11, "IT-SW01", serial="OLD", site_id=1)
        nb = MagicMock()
        nb.dcim.devices.filter.side_effect = [[], [stale, empty]]
        with patch.object(main, "_all_unifi_serials_global", set()):
            result = find_existing_device(nb, "NEW", "IT-SW01", _site(1))
        assert result is empty

    def test_skips_when_unifi_serial_is_empty(self):
        # If the new device has no serial (rare; mac-mode disabled, etc.),
        # do not run replacement logic.
        other = _nb_device(7, "IT-SW01", serial="OLD", site_id=1)
        nb = MagicMock()
        nb.dcim.devices.filter.side_effect = [[], [other]]
        with patch.object(main, "_all_unifi_serials_global", set()):
            result = find_existing_device(nb, "", "IT-SW01", _site(1))
        assert result is None
