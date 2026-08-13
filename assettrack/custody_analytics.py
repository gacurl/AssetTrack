from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from assettrack.custody_accountability import CustodyAccountabilityReport, HolderSummary


MeasureId = Literal[
    "total_time_checked_out",
    "checkout_transactions",
    "number_of_assets",
    "checkout_duration",
    "current_accountability",
]
GroupingId = Literal[
    "holder",
    "asset_type",
    "duration_range",
    "accountability_state",
    "checkout_date",
]


@dataclass(frozen=True)
class AnalyticsSelection:
    measure: MeasureId
    grouping: GroupingId
    label: str


@dataclass(frozen=True)
class AnalyticsRow:
    key: str
    label: str
    value: int
    unit: str


@dataclass(frozen=True)
class AnalyticsDataset:
    selection: AnalyticsSelection
    rows: tuple[AnalyticsRow, ...]


SUPPORTED_ANALYTICS: tuple[AnalyticsSelection, ...] = (
    AnalyticsSelection("total_time_checked_out", "holder", "Total Time Checked Out + MA / Holder"),
    AnalyticsSelection("checkout_transactions", "holder", "Checkout Transactions + MA / Holder"),
    AnalyticsSelection("number_of_assets", "asset_type", "Number of Assets + Asset Type"),
    AnalyticsSelection("checkout_duration", "duration_range", "Checkout Duration + Duration Range"),
    AnalyticsSelection("current_accountability", "accountability_state", "Current Accountability + Accountability State"),
    AnalyticsSelection("checkout_transactions", "checkout_date", "Checkout Transactions + Checkout Date"),
)

SUPPORTED_ANALYTICS_BY_KEY = {
    (selection.measure, selection.grouping): selection for selection in SUPPORTED_ANALYTICS
}

DURATION_BUCKETS: tuple[tuple[str, str, timedelta | None, timedelta | None], ...] = (
    ("lt_8_hours", "< 8 hours", None, timedelta(hours=8)),
    ("8_to_lt_24_hours", "8 to <24 hours", timedelta(hours=8), timedelta(hours=24)),
    ("1_to_lt_3_days", "1 to <3 days", timedelta(days=1), timedelta(days=3)),
    ("3_to_lt_7_days", "3 to <7 days", timedelta(days=3), timedelta(days=7)),
    ("7_plus_days", "7+ days", timedelta(days=7), None),
)


def build_analytics_dataset(
    report: CustodyAccountabilityReport,
    *,
    measure: MeasureId,
    grouping: GroupingId,
) -> AnalyticsDataset:
    selection = SUPPORTED_ANALYTICS_BY_KEY.get((measure, grouping))
    if selection is None:
        raise ValueError(f"unsupported custody analytics selection: {measure} by {grouping}")

    if measure == "total_time_checked_out" and grouping == "holder":
        rows = _total_time_by_holder(report)
    elif measure == "checkout_transactions" and grouping == "holder":
        rows = _transactions_by_holder(report)
    elif measure == "number_of_assets" and grouping == "asset_type":
        rows = _assets_by_type(report)
    elif measure == "checkout_duration" and grouping == "duration_range":
        rows = _duration_distribution(report)
    elif measure == "current_accountability" and grouping == "accountability_state":
        rows = _current_accountability(report)
    elif measure == "checkout_transactions" and grouping == "checkout_date":
        rows = _activity_by_day(report)
    else:
        raise ValueError(f"unsupported custody analytics selection: {measure} by {grouping}")

    return AnalyticsDataset(selection=selection, rows=rows)


def _holder_key(holder: HolderSummary) -> str:
    if holder.holder_id is not None:
        return f"holder:{holder.holder_id}"
    return f"holder:unresolved:{holder.name.casefold()}:{holder.organization.casefold()}"


def _holder_label(holder: HolderSummary) -> str:
    return holder.label or "Unresolved holder"


def _seconds(value: timedelta) -> int:
    return int(value.total_seconds())


def _total_time_by_holder(report: CustodyAccountabilityReport) -> tuple[AnalyticsRow, ...]:
    return tuple(
        AnalyticsRow(
            key=_holder_key(summary.holder),
            label=_holder_label(summary.holder),
            value=_seconds(summary.total_custody_time),
            unit="seconds",
        )
        for summary in report.holders
    )


def _transactions_by_holder(report: CustodyAccountabilityReport) -> tuple[AnalyticsRow, ...]:
    return tuple(
        AnalyticsRow(
            key=_holder_key(summary.holder),
            label=_holder_label(summary.holder),
            value=summary.issue_transaction_count,
            unit="count",
        )
        for summary in report.holders
    )


def _assets_by_type(report: CustodyAccountabilityReport) -> tuple[AnalyticsRow, ...]:
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for asset in report.assets:
        label = asset.equipment_type.strip() or "Unspecified"
        key = label.casefold()
        counts[key] = counts.get(key, 0) + 1
        labels.setdefault(key, label)

    return tuple(
        AnalyticsRow(key=f"asset_type:{key}", label=labels[key], value=counts[key], unit="count")
        for key in sorted(counts, key=lambda item: (labels[item].casefold(), item))
    )


def _duration_distribution(report: CustodyAccountabilityReport) -> tuple[AnalyticsRow, ...]:
    counts = {key: 0 for key, _label, _lower, _upper in DURATION_BUCKETS}
    for asset in report.assets:
        for interval in asset.intervals:
            counts[_duration_bucket_key(interval.elapsed)] += 1

    return tuple(
        AnalyticsRow(key=key, label=label, value=counts[key], unit="count")
        for key, label, _lower, _upper in DURATION_BUCKETS
    )


def _duration_bucket_key(duration: timedelta) -> str:
    for key, _label, lower, upper in DURATION_BUCKETS:
        if lower is not None and duration < lower:
            continue
        if upper is not None and duration >= upper:
            continue
        return key
    raise ValueError(f"unsupported custody duration: {duration}")


def _current_accountability(report: CustodyAccountabilityReport) -> tuple[AnalyticsRow, ...]:
    return (
        AnalyticsRow("checked_in", "Checked In", report.checked_in, "count"),
        AnalyticsRow("checked_out", "Checked Out", report.checked_out, "count"),
        AnalyticsRow("exceptions_unresolved", "Exceptions / Unresolved", report.unresolved, "count"),
    )


def _activity_by_day(report: CustodyAccountabilityReport) -> tuple[AnalyticsRow, ...]:
    counts: dict[str, int] = {}
    for asset in report.assets:
        for interval in asset.intervals:
            day = interval.issue_timestamp.date().isoformat()
            counts[day] = counts.get(day, 0) + 1

    return tuple(
        AnalyticsRow(key=f"checkout_date:{day}", label=day, value=counts[day], unit="count")
        for day in sorted(counts)
    )
