"""Redacted support-bundle construction for UniFi Announcer.

The public support bundle is deliberately assembled from a small allowlist. It
never serializes raw service objects, Protect bootstrap data, device IDs,
credentials, URLs, cookies, signed talkback values, filenames, fingerprints, or
support-log text.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping


_LATENCY_STAGES = (
    "announce_total_ms",
    "tts_ms",
    "pcm_process_ms",
    "encode_ms",
    "upload_ms",
    "play_request_ms",
    "queue_wait_ms",
    "slot_acquire_ms",
    "slot_preflight_ms",
    "slot_direct_upload_ms",
    "slot_sync_ms",
    "slot_settle_ms",
    "slot_prepare_ms",
    "camera_prepare_ms",
)

_SAFE_LAST_PREPARE_FIELDS = (
    "slot_acquire_ms",
    "slot_preflight_ms",
    "slot_direct_upload_ms",
    "slot_sync_ms",
    "slot_settle_ms",
    "slot_prepare_ms",
    "logical_slot",
    "target_count",
    "selection_content_match",
    "content_hit",
    "overwrites",
    "overwrite_skips",
    "content_size",
)


def _number(value: Any) -> int | float | None:
    """Return finite, non-boolean JSON-safe numeric telemetry only."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not isfinite(value):
        return None
    return value


def _safe_histograms(metrics: Mapping[str, Any]) -> dict[str, dict[str, int | float]]:
    raw = metrics.get("histograms")
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, dict[str, int | float]] = {}
    for name in _LATENCY_STAGES:
        item = raw.get(name)
        if not isinstance(item, Mapping):
            continue
        values = {}
        for field in ("count", "sum", "min", "max", "avg"):
            value = _number(item.get(field))
            if value is not None:
                values[field] = value
        if values:
            result[name] = values
    return result


def _safe_counters(metrics: Mapping[str, Any]) -> dict[str, int | float]:
    raw = metrics.get("counters")
    if not isinstance(raw, Mapping):
        return {}
    result = {}
    for name, raw_value in sorted(raw.items()):
        value = _number(raw_value)
        if value is not None:
            result[str(name)] = value
    return result


def _target_aliases(
    target_catalog: Mapping[str, Any],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    aliases: dict[str, str] = {}
    result = []
    raw_targets = target_catalog.get("targets")
    if not isinstance(raw_targets, list):
        return aliases, result

    for index, item in enumerate(raw_targets, 1):
        if not isinstance(item, Mapping):
            continue
        raw_name = str(item.get("name") or "")
        alias = f"target_{index}"
        if raw_name:
            aliases[raw_name] = alias
        target_type = str(item.get("type") or "unknown")
        entry: dict[str, Any] = {
            "target": alias,
            "type": target_type if target_type in {"chime", "camera"} else "unknown",
            "queue_depth": _number(item.get("queue_depth")) or 0,
        }
        capabilities = item.get("capabilities")
        if isinstance(capabilities, Mapping):
            entry["capabilities"] = {
                str(key): value
                for key, value in sorted(capabilities.items())
                if isinstance(value, bool)
            }
        if entry["type"] == "camera":
            status = str(item.get("status") or "unavailable")
            entry["status"] = (
                status if status in {"available", "unavailable"} else "unknown"
            )
            model = item.get("model")
            if isinstance(model, str) and 0 < len(model) <= 128:
                entry["model"] = model
            compatibility = item.get("compatibility")
            if compatibility in {"physically_validated", "experimental_opt_in"}:
                entry["compatibility"] = compatibility
        result.append(entry)
    return aliases, result


def _safe_groups(
    target_catalog: Mapping[str, Any], aliases: Mapping[str, str]
) -> list[dict[str, Any]]:
    raw_groups = target_catalog.get("groups")
    if not isinstance(raw_groups, list):
        return []
    groups = []
    for index, item in enumerate(raw_groups, 1):
        if not isinstance(item, Mapping):
            continue
        members = item.get("members")
        safe_members = []
        if isinstance(members, list):
            safe_members = [aliases[name] for name in members if name in aliases]
        capabilities = item.get("capabilities")
        safe_capabilities = {}
        if isinstance(capabilities, Mapping):
            safe_capabilities = {
                str(key): value
                for key, value in sorted(capabilities.items())
                if isinstance(value, bool)
            }
        groups.append(
            {
                "group": f"group_{index}",
                "members": safe_members,
                "capabilities": safe_capabilities,
            }
        )
    return groups


def _safe_slot_state(slot_status: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ready": bool(slot_status.get("ready")),
        "mode": str(slot_status.get("mode") or "unknown"),
        "slot_count": _number(slot_status.get("slot_count")) or 0,
        "busy_slots": [
            value
            for value in (slot_status.get("busy_slots") or [])
            if isinstance(value, int) and not isinstance(value, bool)
        ],
        "legacy_orphans": _number(slot_status.get("legacy_orphans")) or 0,
        "error_present": bool(slot_status.get("last_error")),
    }

    slots = slot_status.get("slots")
    summaries = []
    if isinstance(slots, Mapping):
        content_reuse = slot_status.get("content_reuse")
        assignments = (
            content_reuse.get("assignments")
            if isinstance(content_reuse, Mapping)
            else {}
        )
        for raw_number, raw_slot in sorted(
            slots.items(), key=lambda pair: str(pair[0])
        ):
            if not isinstance(raw_slot, Mapping):
                continue
            bindings = raw_slot.get("bindings")
            binding_count = len(bindings) if isinstance(bindings, Mapping) else 0
            trusted_count = 0
            assignment = (
                assignments.get(str(raw_number))
                if isinstance(assignments, Mapping)
                else None
            )
            if isinstance(assignment, Mapping):
                trusted_count = sum(
                    1
                    for value in assignment.values()
                    if isinstance(value, Mapping) and value.get("trusted") is True
                )
            try:
                logical_slot = int(raw_number)
            except (TypeError, ValueError):
                continue
            summaries.append(
                {
                    "logical_slot": logical_slot,
                    "binding_count": binding_count,
                    "trusted_binding_count": trusted_count,
                }
            )
    result["slots"] = summaries

    reuse = slot_status.get("content_reuse")
    if isinstance(reuse, Mapping):
        result["trusted_bindings"] = _number(reuse.get("trusted_bindings")) or 0
        last_prepare = reuse.get("last_prepare")
        if isinstance(last_prepare, Mapping):
            safe_last_prepare = {}
            for field in _SAFE_LAST_PREPARE_FIELDS:
                raw_value = last_prepare.get(field)
                if isinstance(raw_value, bool):
                    safe_last_prepare[field] = raw_value
                else:
                    value = _number(raw_value)
                    if value is not None:
                        safe_last_prepare[field] = value
            if safe_last_prepare:
                result["last_prepare"] = safe_last_prepare
    return result


def _safe_health(health: Mapping[str, Any]) -> dict[str, Any]:
    result = {"status": str(health.get("status") or "unknown")}
    components = health.get("components")
    if isinstance(components, Mapping):
        result["components"] = {
            str(name): {"status": str(value.get("status") or "unknown")}
            for name, value in sorted(components.items())
            if isinstance(value, Mapping)
        }
    return result


def _safe_cache(cache: Mapping[str, Any]) -> dict[str, int | float]:
    result = {}
    for name in ("files", "bytes", "evicted", "max_files", "max_bytes"):
        value = _number(cache.get(name))
        if value is not None:
            result[name] = value
    return result


def _safe_media_limits(media_limits: Any | None) -> dict[str, int | float]:
    if media_limits is None:
        return {}
    result = {}
    for public, attr in (
        ("max_input_bytes", "max_input_bytes"),
        ("max_output_bytes", "max_output_bytes"),
        ("max_duration_seconds", "max_duration_seconds"),
        ("normalize_timeout_seconds", "normalize_timeout_seconds"),
    ):
        value = _number(getattr(media_limits, attr, None))
        if value is not None:
            result[public] = value
    return result


def _safe_tested_firmware(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, list[str]] = {}
    for name, versions in sorted(value.items()):
        if not isinstance(name, str) or not isinstance(versions, list):
            continue
        clean = [
            version
            for version in versions
            if isinstance(version, str) and 0 < len(version) <= 64
        ]
        if clean:
            result[name] = clean
    return result


def _warnings(
    *,
    release: Mapping[str, Any],
    health: Mapping[str, Any],
    targets: list[dict[str, Any]],
    slots: Mapping[str, Any],
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if str(release.get("git_sha") or "unknown") == "unknown":
        warnings.append({"code": "build_revision_unknown", "severity": "warning"})
    if health.get("status") != "ok":
        warnings.append({"code": "service_health_degraded", "severity": "warning"})
    if not slots.get("ready"):
        warnings.append({"code": "dynamic_tts_not_ready", "severity": "warning"})
    if (_number(slots.get("legacy_orphans")) or 0) > 0:
        warnings.append({"code": "legacy_orphans_present", "severity": "warning"})
    for target in targets:
        if target.get("type") != "camera":
            continue
        alias = str(target.get("target"))
        if target.get("status") != "available":
            warnings.append(
                {
                    "code": "camera_unavailable",
                    "severity": "warning",
                    "target": alias,
                }
            )
        elif target.get("compatibility") == "experimental_opt_in":
            warnings.append(
                {
                    "code": "camera_experimental_opt_in",
                    "severity": "info",
                    "target": alias,
                }
            )
        elif target.get("compatibility") != "physically_validated":
            warnings.append(
                {
                    "code": "camera_compatibility_unproven",
                    "severity": "warning",
                    "target": alias,
                }
            )
    return warnings


def build_support_bundle(
    *,
    release: Mapping[str, Any],
    health: Mapping[str, Any],
    target_catalog: Mapping[str, Any],
    slot_status: Mapping[str, Any],
    cache_stats: Mapping[str, Any],
    metrics: Mapping[str, Any],
    media_limits: Any | None = None,
) -> dict[str, Any]:
    """Build a shareable, pseudonymized support snapshot from allowlisted state."""
    aliases, targets = _target_aliases(target_catalog)
    groups = _safe_groups(target_catalog, aliases)
    safe_health = _safe_health(health)
    safe_slots = _safe_slot_state(slot_status)
    safe_release: dict[str, Any] = {
        "version": str(release.get("version") or "unknown"),
        "git_sha": str(release.get("git_sha") or "unknown"),
        "service": "unifi-announcer",
    }
    protocols = release.get("protocols")
    if isinstance(protocols, Mapping):
        safe_release["protocols"] = {
            str(name): str(value)
            for name, value in sorted(protocols.items())
            if isinstance(name, str) and isinstance(value, str)
        }
    tested_firmware = _safe_tested_firmware(release.get("tested_firmware"))
    if tested_firmware:
        safe_release["tested_firmware"] = tested_firmware

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "redaction": {
            "target_and_group_names": "pseudonymized",
            "device_identifiers": "omitted",
            "credentials_tokens_urls": "omitted",
            "filenames_and_content_fingerprints": "omitted",
            "support_logs": "omitted",
        },
        "release": safe_release,
        "health": safe_health,
        "targets": targets,
        "groups": groups,
        "dynamic_tts": safe_slots,
        "tts_cache": _safe_cache(cache_stats),
        "media_ingestion": _safe_media_limits(media_limits),
        "metrics": {
            "counters": _safe_counters(metrics),
            "latency_stages": _safe_histograms(metrics),
        },
        "compatibility": {
            "basis": "capability_state_and_physical_evidence",
            "warnings": _warnings(
                release=safe_release,
                health=safe_health,
                targets=targets,
                slots=safe_slots,
            ),
        },
    }
