"""Tests for community device specs integration."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest

from main import (
    _load_community_specs,
    _lookup_community_specs,
    _resolve_device_specs,
)


# ---------------------------------------------------------------------------
#  Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_community_specs():
    """Reset the cached community specs between tests."""
    import main
    main._community_specs = None
    yield
    main._community_specs = None


@pytest.fixture
def sample_community_json():
    """Minimal community specs JSON structure."""
    return {
        "by_part": {
            "USW-PRO-48-POE": {
                "model_name": "UniFi Switch 48 Pro PoE",
                "slug": "ubiquiti-usw-pro-48-poe",
                "part_number": "USW-PRO-48-POE",
                "u_height": 1,
                "is_full_depth": False,
                "airflow": "front-to-rear",
                "weight": 4.5,
                "weight_unit": "kg",
                "interfaces": [
                    {"name": "Port 1", "type": "1000base-t", "poe_mode": "pse", "poe_type": "type2-ieee802.3at"},
                ],
                "console_ports": [
                    {"name": "Console", "type": "rj-45"},
                ],
                "power_ports": [
                    {"name": "PS1", "type": "iec-60320-c14", "maximum_draw": 600},
                ],
            },
            "UAP-AC-LITE": {
                "model_name": "UniFi AP AC Lite",
                "slug": "ubiquiti-uap-ac-lite",
                "part_number": "UAP-AC-LITE",
                "u_height": 0,
                "interfaces": [
                    {"name": "eth0", "type": "1000base-t"},
                ],
            },
        },
        "by_model": {
            "UniFi Switch 48 Pro PoE": {
                "model_name": "UniFi Switch 48 Pro PoE",
                "slug": "ubiquiti-usw-pro-48-poe",
                "part_number": "USW-PRO-48-POE",
                "u_height": 1,
            },
        },
    }


# ---------------------------------------------------------------------------
#  _load_community_specs
# ---------------------------------------------------------------------------

class TestLoadCommunitySpecs:
    def test_loads_from_json_file(self):
        """Should load the actual bundled JSON file."""
        specs = _load_community_specs()
        assert "by_part" in specs
        assert "by_model" in specs
        assert len(specs["by_part"]) > 0

    def test_caches_result(self):
        """Second call returns cached result (no file I/O)."""
        first = _load_community_specs()
        second = _load_community_specs()
        assert first is second

    def test_missing_file_returns_empty(self):
        """Should return empty dicts if file doesn't exist."""
        import main
        with patch("os.path.exists", return_value=False):
            main._community_specs = None
            specs = _load_community_specs()
            assert specs == {"by_part": {}, "by_model": {}}


# ---------------------------------------------------------------------------
#  _lookup_community_specs
# ---------------------------------------------------------------------------

class TestLookupCommunitySpecs:
    def test_exact_part_number(self, sample_community_json):
        import main
        main._community_specs = sample_community_json
        result = _lookup_community_specs(part_number="USW-PRO-48-POE")
        assert result is not None
        assert result["slug"] == "ubiquiti-usw-pro-48-poe"

    def test_case_insensitive_part_number(self, sample_community_json):
        import main
        main._community_specs = sample_community_json
        result = _lookup_community_specs(part_number="usw-pro-48-poe")
        assert result is not None
        assert result["slug"] == "ubiquiti-usw-pro-48-poe"

    def test_mixed_case_part_number(self, sample_community_json):
        """The actual case: hardcoded has 'USW-Pro-48-PoE', community has 'USW-PRO-48-POE'."""
        import main
        main._community_specs = sample_community_json
        result = _lookup_community_specs(part_number="USW-Pro-48-PoE")
        assert result is not None

    def test_model_name_lookup(self, sample_community_json):
        import main
        main._community_specs = sample_community_json
        result = _lookup_community_specs(model="UniFi Switch 48 Pro PoE")
        assert result is not None

    def test_returns_none_for_unknown(self, sample_community_json):
        import main
        main._community_specs = sample_community_json
        result = _lookup_community_specs(part_number="NONEXISTENT-MODEL")
        assert result is None

    def test_returns_none_when_no_args(self, sample_community_json):
        import main
        main._community_specs = sample_community_json
        result = _lookup_community_specs()
        assert result is None


# ---------------------------------------------------------------------------
#  _resolve_device_specs
# ---------------------------------------------------------------------------

class TestResolveDeviceSpecs:
    def test_known_hardcoded_model(self, sample_community_json):
        """US48PRO has hardcoded specs with part_number USW-Pro-48-PoE."""
        import main
        main._community_specs = sample_community_json
        result = _resolve_device_specs("US48PRO")
        assert result is not None
        # Hardcoded values should be present
        assert "ports" in result
        assert result["poe_budget"] == 600
        # Community values should be merged in
        assert result.get("interfaces") is not None or result.get("console_ports") is not None

    def test_unknown_model_returns_none(self, sample_community_json):
        import main
        main._community_specs = sample_community_json
        result = _resolve_device_specs("TOTALLY-UNKNOWN-XYZ")
        assert result is None

    def test_hardcoded_overrides_community(self, sample_community_json):
        """Hardcoded values should win over community values."""
        import main
        main._community_specs = sample_community_json
        result = _resolve_device_specs("US48PRO")
        if result:
            # Hardcoded has part_number "USW-Pro-48-PoE" (not "USW-PRO-48-POE")
            assert result["part_number"] == "USW-Pro-48-PoE"

    def test_community_only_model(self, sample_community_json):
        """A model only in community (not in UNIFI_MODEL_SPECS) can still be found via part_number=model fallback."""
        import main
        main._community_specs = sample_community_json
        # UAP-AC-LITE is both a hardcoded part_number AND a community key
        result = _resolve_device_specs("UAP-AC-Lite")
        assert result is not None


# ---------------------------------------------------------------------------
#  is_full_depth default policy (switches default to non-full-depth)
# ---------------------------------------------------------------------------

class TestSwitchDepthDefault:
    """Switch device-types must default to is_full_depth=False unless specs
    explicitly override. This prevents rack-occupancy conflicts when a known
    community spec is missing."""

    def test_relax_returns_true_when_already_false(self):
        import main
        dt = SimpleNamespace(id=1, is_full_depth=False, save=MagicMock())
        assert main._try_relax_device_type_depth(MagicMock(), dt, "USL24PB") is True
        dt.save.assert_not_called()

    def test_relax_flips_to_false_when_specs_silent(self):
        import main
        dt = SimpleNamespace(id=1, is_full_depth=True, save=MagicMock())
        with patch.object(main, "_resolve_device_specs", return_value={}):
            result = main._try_relax_device_type_depth(MagicMock(), dt, "UNKNOWN-MODEL")
        assert result is True
        assert dt.is_full_depth is False
        dt.save.assert_called_once()

    def test_relax_refuses_when_specs_say_full_depth(self):
        import main
        dt = SimpleNamespace(id=1, is_full_depth=True, save=MagicMock())
        with patch.object(main, "_resolve_device_specs", return_value={"is_full_depth": True}):
            result = main._try_relax_device_type_depth(MagicMock(), dt, "US-24")
        assert result is False
        assert dt.is_full_depth is True  # unchanged
        dt.save.assert_not_called()

    def test_relax_handles_none_device_type(self):
        import main
        assert main._try_relax_device_type_depth(MagicMock(), None, "X") is False

    def test_relax_logs_and_returns_false_on_save_error(self):
        import main
        dt = SimpleNamespace(id=1, is_full_depth=True, save=MagicMock(side_effect=Exception("save failed")))
        with patch.object(main, "_resolve_device_specs", return_value={}):
            result = main._try_relax_device_type_depth(MagicMock(), dt, "X")
        assert result is False


class TestHardcodedSwitchDepth:
    """Compact switches hardcoded with is_full_depth=False."""

    def test_usl24pb_is_full_depth_false(self):
        from unifi.model_specs import UNIFI_MODEL_SPECS
        assert UNIFI_MODEL_SPECS["USL24PB"]["is_full_depth"] is False

    def test_usw_pro_24_is_full_depth_false(self):
        from unifi.model_specs import UNIFI_MODEL_SPECS
        assert UNIFI_MODEL_SPECS["USW-PRO-24"]["is_full_depth"] is False
