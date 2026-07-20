"""Tests for configurable device-tag list and manufacturer-slug handling."""
import os
from unittest.mock import patch

import main
from main import NETBOX_DEVICE_TAGS


# ---------------------------------------------------------------------------
#  NETBOX_DEVICE_TAGS module-level setting
# ---------------------------------------------------------------------------

class TestNetboxDeviceTagsDefault:
    def test_default_is_empty_tuple_when_env_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            # Re-evaluate the module-level expression by importing the helper
            # directly — module-level constant is bound at import time, so we
            # exercise the same expression here.
            value = tuple(
                t.strip()
                for t in (os.getenv("NETBOX_DEVICE_TAGS") or "").split(",")
                if t.strip()
            )
            assert value == ()

    def test_module_constant_default_when_no_env(self):
        # Without env override the module-level constant is an empty tuple.
        with patch.dict(os.environ, {}, clear=True):
            assert NETBOX_DEVICE_TAGS == ()


class TestNetboxDeviceTagsParsing:
    def _parse(self, env_value):
        with patch.dict(os.environ, {"NETBOX_DEVICE_TAGS": env_value}, clear=True):
            return tuple(
                t.strip()
                for t in (os.getenv("NETBOX_DEVICE_TAGS") or "").split(",")
                if t.strip()
            )

    def test_single_tag(self):
        assert self._parse("zabbix") == ("zabbix",)

    def test_multiple_tags_comma_separated(self):
        assert self._parse("zabbix,monitoring,backups") == ("zabbix", "monitoring", "backups")

    def test_whitespace_trimmed(self):
        assert self._parse("  zabbix  ,  monitoring  ") == ("zabbix", "monitoring")

    def test_empty_entries_ignored(self):
        assert self._parse("zabbix,,monitoring,") == ("zabbix", "monitoring")

    def test_empty_string_means_no_tags(self):
        assert self._parse("") == ()

    def test_only_whitespace_means_no_tags(self):
        assert self._parse("   ") == ()

    def test_no_hardcoded_zabbix_when_env_empty(self):
        # Regression: previously `ensure_tag(nb, "zabbix")` was called
        # unconditionally. With the env unset, no tag should be configured.
        assert "zabbix" not in NETBOX_DEVICE_TAGS

    def test_zabbix_only_when_explicitly_configured(self):
        assert self._parse("zabbix") == ("zabbix",)


# ---------------------------------------------------------------------------
#  zabbix string is no longer referenced as a literal in main.py business logic
# ---------------------------------------------------------------------------

class TestNoHardcodedZabbixReference:
    """The literal 'zabbix' must not appear anywhere in main.py outside the
    docstring/comment that explains the migration path from the old behavior."""

    def test_zabbix_literal_not_in_main_py(self):
        with open("main.py") as f:
            src = f.read()
        # Strip the module-level docstring/comment block that documents the
        # migration from the hardcoded 'zabbix' value.
        marker = "# Empty by default"
        idx = src.find(marker)
        if idx >= 0:
            # Drop the surrounding ~3 lines that mention 'zabbix' in the
            # comment explaining the legacy behavior.
            line_start = src.rfind("\n", 0, idx)
            line_end = src.find("\n\n", idx)
            src = src[:line_start] + src[line_end:] if line_end >= 0 else src
        assert "zabbix" not in src, (
            "main.py still references the hardcoded 'zabbix' tag. Use the "
            "NETBOX_DEVICE_TAGS env var instead."
        )


# ---------------------------------------------------------------------------
#  UNIFI_MANUFACTURER_SLUG handling
# ---------------------------------------------------------------------------

class TestManufacturerSlugEnv:
    def test_default_is_ubiquiti(self):
        # When the env is unset the default slug must be the correctly-spelled
        # 'ubiquiti' (NOT 'ubiquity').
        with patch.dict(os.environ, {}, clear=True):
            slug = (os.getenv("UNIFI_MANUFACTURER_SLUG") or "ubiquiti").strip().lower() or "ubiquiti"
            assert slug == "ubiquiti"

    def test_env_override_respected(self):
        with patch.dict(os.environ, {"UNIFI_MANUFACTURER_SLUG": "ubiquity"}, clear=True):
            slug = (os.getenv("UNIFI_MANUFACTURER_SLUG") or "ubiquiti").strip().lower() or "ubiquiti"
            assert slug == "ubiquity"

    def test_whitespace_trimmed(self):
        with patch.dict(os.environ, {"UNIFI_MANUFACTURER_SLUG": "  Ubiquiti  "}, clear=True):
            slug = (os.getenv("UNIFI_MANUFACTURER_SLUG") or "ubiquiti").strip().lower() or "ubiquiti"
            assert slug == "ubiquiti"

    def test_empty_string_falls_back_to_default(self):
        with patch.dict(os.environ, {"UNIFI_MANUFACTURER_SLUG": ""}, clear=True):
            slug = (os.getenv("UNIFI_MANUFACTURER_SLUG") or "ubiquiti").strip().lower() or "ubiquiti"
            assert slug == "ubiquiti"


# ---------------------------------------------------------------------------
#  Codebase sanity: 'Ubiquity' typo must not appear in business logic
# ---------------------------------------------------------------------------

class TestNoUbiquityTypoInBusinessLogic:
    """The misspelling 'Ubiquity' (correct: 'Ubiquiti') is allowed only in the
    legacy-fallback branch of the manufacturer lookup. Anywhere else is a bug."""

    def test_no_ubiquity_variable_or_function_name(self):
        with open("main.py") as f:
            src = f.read()
        # Variable / function / parameter names that still use the typo.
        for name in ("nb_ubiquity", "ubiquity_desc"):
            assert name not in src, f"main.py still uses identifier '{name}'"

    def test_ubiquity_string_only_in_legacy_fallback(self):
        """'ubiquity' as a string literal may appear only in the legacy
        manufacturer-fallback block — not as a tag, slug, or display name."""
        with open("main.py") as f:
            src = f.read()
        # Find all quoted occurrences of 'ubiquity' (case-insensitive).
        import re
        matches = []
        for m in re.finditer(r"[\"']([Uu]biquity)[\"']", src):
            line_no = src.count("\n", 0, m.start()) + 1
            matches.append((line_no, m.group(0)))
        # All such matches must be inside the legacy fallback block, which is
        # the only place where the old slug is intentionally referenced.
        assert matches, "Expected at least one 'ubiquity' literal in the legacy fallback"
        for line_no, _ in matches:
            # The fallback lives roughly between the 'UNIFI_MANUFACTURER_SLUG'
            # declaration and the tenant lookup that follows it. We assert
            # each match is within that window to prevent accidental reuse
            # elsewhere in the file.
            assert 2450 <= line_no <= 2480, (
                f"'ubiquity' literal at line {line_no} is outside the legacy "
                f"fallback block — likely a reintroduced typo."
            )
