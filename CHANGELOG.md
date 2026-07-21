# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added
- Python packaging metadata added (`pyproject.toml`, `netbox_unifi_sync/version.py`, `netbox-plugin.yaml`) to support PyPI releases.
- GitHub Actions release pipeline updated for tag-driven GitHub Releases and PyPI trusted publishing via OIDC.
- Gateway and DNS are now read from UniFi network config (`gateway_ip`, `dhcpd_dns_1-4`) for DHCP-to-static IP conversion.
- Fallback env vars `DEFAULT_GATEWAY` and `DEFAULT_DNS` when UniFi network config lacks gateway/DNS.
- 20 new unit tests covering `_get_network_info_for_ip`, `extract_dhcp_ranges_from_unifi` network info, and `is_ip_in_dhcp_range`.
- TLS verification configuration flags:
  - `UNIFI_VERIFY_SSL` (default: `true`)
  - `NETBOX_VERIFY_SSL` (default: `true`)
- UniFi session cache control:
  - `UNIFI_PERSIST_SESSION` (default: `true`)
- Robust integer parsing helper for runtime env vars (used for sync interval and cleanup grace period).
- Existing-device lookup now falls back to same-name + empty-serial at the target site, adopting the record and filling its serial instead of creating a duplicate. The `unifi-keep-serial` tag (and `unifi-keep-all`) opts a device out of the auto-fill.
- New `UNIFI_NAME_CONFLICT_POLICY=replace|new` (default: `replace`) controls behavior when a UniFi device reuses a name that already exists in NetBox under a different stale serial (physical-replacement scenario). `replace` adopts the existing record and overwrites serial/device_type/custom fields; `new` creates a new device with a suffixed name.
- Device-type creation now defaults all switches (role `LAN`) to `is_full_depth=false` to avoid spurious rack-occupancy conflicts when specs are missing. Hardcoded specs added for `USL24PB` and `USW-PRO-24` (compact switches).
- IP-address sync now adopts orphan records (matching host under any mask, no tenant) and rebinds them to the current device, clearing stale `primary_ip4` references on previous owners.

### Fixed
- Devices that already exist in NetBox with an empty serial no longer cause duplicate creation (or a spurious `{name}_{serial}` variant) on the next sync. The existing record is now adopted and its serial is filled in.
- Duplicate-IP errors during IP-address assignment no longer crash the device sync; the existing record is adopted, normalized to the current tenant/VRF, and rebound to the device's `vlan.1` interface.
- `device_types.create` recovery now handles `already exists` / `constraint violated` messages in addition to the legacy Postgres duplicate-key text, and falls back to a `slug` lookup when `model` and `part_number` miss.
- `devices.create` race-recovery now matches the NetBox 4.x `dcim_device_unique_name_site_tenant` constraint text (not just the legacy "Device name must be unique per site").
- Device-type updates that fail with a rack/position conflict now attempt to relax `is_full_depth=false` on the target type (respecting explicit `True` specs) and retry, so device-type rotations on rack-mounted switches no longer fail.

### Changed
- Runtime startup validation logs now use `logger.error(...)` for fail-fast config checks (instead of `logger.exception(...)` outside `except` blocks).
- NetBox HTTP session verify behavior is now driven by `NETBOX_VERIFY_SSL`.
- UniFi request verify behavior is now driven by `UNIFI_VERIFY_SSL`.
- `README.md`, `docs/configuration.md`, `docs/architecture.md`, and `docs/troubleshooting.md` updated to match current TLS/session behavior.
- Docker image metadata source URL corrected to the active repository.

### Security
- UniFi session cache file writes now enforce restrictive permissions (`0600`).
- Integration API auth headers are no longer persisted to session cache on disk.

### Removed
- Raw auto-generated git-log changelog format replaced by structured release notes.

## 2026-02-16

### Changed
- Repository cleanup and documentation alignment with current implementation.
- CI workflow updated to install `pytest` explicitly while keeping runtime dependencies minimal.
- Dockerfile aligned with current runtime files.
- LXC scripts updated for current repository URL and simplified install flow.

### Removed
- Unused standalone files: `unifi_client.py`, `config.py`, `exceptions.py`, `utils.py`.
- Dead code and unused imports across core modules and tests.

## 2025-02-12

### Added
- Unit test suite and CI pipeline.
- Thread limits configurable via environment variables.

### Removed
- `README-old.md` (obsolete).

### Fixed
- `.gitignore` updated with key file ignores.

## 2025-02-11

### Added
- Community device specs bundle integration.
- Generic template sync for interface/console/power templates.
- NetBox cleanup workflow.
- Auto-create device types from discovered models.
- Continuous sync loop via `SYNC_INTERVAL`.

### Fixed
- Case-insensitive part number lookup behavior.

## 2025-02-10

### Added
- DHCP auto-discovery from UniFi network configuration.
- Merge of discovered DHCP ranges with manual `DHCP_RANGES`.
- `DHCP_AUTO_DISCOVER` toggle.

## 2025-02-09

### Added
- Built-in UniFi model specs and interface template sync.
- Device type enrichment (part number, U height, PoE budget).

### Changed
- Concurrency/race condition hardening for tagging paths.

## 2025-02-08

### Added
- Cable sync and stale/offline device handling.

### Improved
- Reliability improvements in concurrent controller processing.
