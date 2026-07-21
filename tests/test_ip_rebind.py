"""Tests for IP-address adoption and rebinding logic.

When a host IP already exists in NetBox under a different mask (e.g. /24
instead of /16 derived from a parent prefix), or under no tenant, the sync
must adopt the existing record and rebind it to the current device's vlan.1
interface instead of failing the device sync with "Duplicate IP".
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from main import _clear_primary_ip_owner, _find_ip_by_host, _normalize_adopted_ip


def _ip(id_, address, tenant_id=None, vrf_id=None, obj_id=None):
    return SimpleNamespace(
        id=id_,
        address=address,
        tenant_id=tenant_id,
        vrf_id=vrf_id,
        assigned_object_id=obj_id,
        save=MagicMock(),
    )


# ---------------------------------------------------------------------------
#  _find_ip_by_host
# ---------------------------------------------------------------------------

class TestFindIpByHost:
    def test_returns_none_on_empty_host(self):
        nb = MagicMock()
        assert _find_ip_by_host(nb, "") is None

    def test_returns_none_when_no_candidates(self):
        nb = MagicMock()
        nb.ipam.ip_addresses.filter.return_value = []
        assert _find_ip_by_host(nb, "10.0.0.1") is None

    def test_finds_record_with_different_mask(self):
        """Bare-IP lookup must match records stored under any mask."""
        existing = _ip(1080, "192.0.2.10/24")
        nb = MagicMock()
        nb.ipam.ip_addresses.filter.return_value = [existing]
        result = _find_ip_by_host(nb, "192.0.2.10")
        assert result is existing
        # Filter must NOT include tenant_id / vrf_id — orphan IPs lack them.
        kwargs = nb.ipam.ip_addresses.filter.call_args.kwargs
        assert kwargs == {"address": "192.0.2.10"}

    def test_finds_record_with_no_tenant_set(self):
        """Orphan record with tenant=None must still be adoptable."""
        existing = _ip(1080, "192.0.2.10/24", tenant_id=None)
        nb = MagicMock()
        nb.ipam.ip_addresses.filter.return_value = [existing]
        tenant = SimpleNamespace(id=1)
        vrf = SimpleNamespace(id=5)
        result = _find_ip_by_host(nb, "192.0.2.10", tenant=tenant, vrf=vrf)
        assert result is existing

    def test_prefers_record_already_bound_to_interface(self):
        iface = SimpleNamespace(id=42)
        bound = _ip(1080, "192.0.2.10/24", obj_id=42)
        other = _ip(1081, "192.0.2.10/16", obj_id=99)
        nb = MagicMock()
        # Order is intentionally mixed; preferred should win regardless.
        nb.ipam.ip_addresses.filter.return_value = [other, bound]
        result = _find_ip_by_host(nb, "192.0.2.10", prefer_interface=iface)
        assert result is bound

    def test_falls_back_to_first_when_multiple(self, caplog):
        a = _ip(1, "192.0.2.10/24")
        b = _ip(2, "192.0.2.10/16")
        nb = MagicMock()
        nb.ipam.ip_addresses.filter.return_value = [a, b]
        with caplog.at_level("WARNING"):
            result = _find_ip_by_host(nb, "192.0.2.10")
        assert result is a  # first wins

    def test_lookup_exception_returns_none(self):
        nb = MagicMock()
        nb.ipam.ip_addresses.filter.side_effect = RuntimeError("boom")
        assert _find_ip_by_host(nb, "10.0.0.1") is None


# ---------------------------------------------------------------------------
#  _normalize_adopted_ip
# ---------------------------------------------------------------------------

class TestNormalizeAdoptedIp:
    def test_sets_missing_tenant(self):
        ip = _ip(7, "10.0.0.1/24", tenant_id=None)
        tenant = SimpleNamespace(id=3)
        _normalize_adopted_ip(ip, tenant, vrf=None)
        assert ip.tenant == 3
        ip.save.assert_called_once()

    def test_sets_missing_vrf(self):
        ip = _ip(7, "10.0.0.1/24", tenant_id=3, vrf_id=None)
        tenant = SimpleNamespace(id=3)
        vrf = SimpleNamespace(id=9)
        _normalize_adopted_ip(ip, tenant, vrf)
        assert ip.vrf == 9
        ip.save.assert_called_once()

    def test_no_change_when_already_correct(self):
        ip = _ip(7, "10.0.0.1/24", tenant_id=3, vrf_id=9)
        tenant = SimpleNamespace(id=3)
        vrf = SimpleNamespace(id=9)
        _normalize_adopted_ip(ip, tenant, vrf)
        ip.save.assert_not_called()

    def test_save_failure_is_logged_not_raised(self, caplog):
        ip = _ip(7, "10.0.0.1/24", tenant_id=None)
        ip.save.side_effect = Exception("simulated save failure")
        tenant = SimpleNamespace(id=3)
        with caplog.at_level("WARNING"):
            _normalize_adopted_ip(ip, tenant, vrf=None)
        # Must not raise.
        assert ip.tenant == 3

    def test_none_ip_is_noop(self):
        # Should not raise.
        _normalize_adopted_ip(None, tenant=None, vrf=None)



# ---------------------------------------------------------------------------
#  _clear_primary_ip_owner
# ---------------------------------------------------------------------------



class TestClearPrimaryIpOwner:
    def _setup(self, ip_id, owner_id, owner_primary_id):
        target_iface = SimpleNamespace(id=42)
        target_device = SimpleNamespace(id=100, name="new-owner")
        nb_ip = _ip(ip_id, "10.0.0.5/24", obj_id=99)  # bound elsewhere
        owner = SimpleNamespace(
            id=owner_id, name=f"dev-{owner_id}",
            primary_ip4=(SimpleNamespace(id=ip_id) if owner_primary_id == ip_id else None),
            save=MagicMock(),
        )
        nb = MagicMock()
        nb.dcim.interfaces.get.return_value = SimpleNamespace(
            id=99, device=SimpleNamespace(id=owner_id),
        )
        nb.dcim.devices.get.return_value = owner
        return nb, nb_ip, target_iface, target_device, owner

    def test_clears_when_ip_is_owner_primary(self):
        nb, nb_ip, tiface, tdev, owner = self._setup(ip_id=7, owner_id=50, owner_primary_id=7)
        _clear_primary_ip_owner(nb, nb_ip, tiface, tdev, "newdev")
        owner.save.assert_called_once()
        assert owner.primary_ip4 is None

    def test_skips_when_ip_not_owner_primary(self):
        nb, nb_ip, tiface, tdev, owner = self._setup(ip_id=7, owner_id=50, owner_primary_id=None)
        _clear_primary_ip_owner(nb, nb_ip, tiface, tdev, "newdev")
        owner.save.assert_not_called()

    def test_skips_when_owner_is_target_device(self):
        nb, nb_ip, tiface, tdev, owner = self._setup(ip_id=7, owner_id=100, owner_primary_id=7)
        _clear_primary_ip_owner(nb, nb_ip, tiface, tdev, "newdev")
        owner.save.assert_not_called()

    def test_skips_when_ip_unassigned(self):
        nb = MagicMock()
        nb_ip = _ip(7, "10.0.0.5/24", obj_id=None)
        tiface = SimpleNamespace(id=42)
        tdev = SimpleNamespace(id=100, name="x")
        _clear_primary_ip_owner(nb, nb_ip, tiface, tdev, "x")
        nb.dcim.interfaces.get.assert_not_called()

    def test_skips_when_already_on_target_interface(self):
        nb = MagicMock()
        tiface = SimpleNamespace(id=42)
        nb_ip = _ip(7, "10.0.0.5/24", obj_id=42)  # bound to target
        tdev = SimpleNamespace(id=100, name="x")
        _clear_primary_ip_owner(nb, nb_ip, tiface, tdev, "x")
        nb.dcim.interfaces.get.assert_not_called()

    def test_silent_on_lookup_failure(self):
        nb = MagicMock()
        nb.dcim.interfaces.get.return_value = None
        nb_ip = _ip(7, "10.0.0.5/24", obj_id=99)
        tiface = SimpleNamespace(id=42)
        tdev = SimpleNamespace(id=100, name="x")
        # Must not raise even when interface lookup returns None.
        _clear_primary_ip_owner(nb, nb_ip, tiface, tdev, "x")
