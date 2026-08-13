# Custody Analytics Dashboard

Use this dashboard when operators need a quick printable chart from AssetTrack custody history.

## Where to find it

1. Log in.
2. Open `Reports`.
3. Select `Custody Analytics`.

## Generate a chart

Choose:

1. `Measure`
2. `Group By`
3. `Chart Type`
4. `Generate`

Only approved Measure and Group By combinations are available for reporting.

## Measures

- `Total Time Checked Out`
- `Checkout Transactions`
- `Number of Assets`
- `Checkout Duration`
- `Current Accountability`

## Group By choices

- `MA / Holder`
- `Asset Type`
- `Duration Range`
- `Accountability State`
- `Checkout Date`

## Chart types

- `Bar` for holder, asset type, and current accountability comparisons
- `Histogram` for checkout duration ranges
- `Line` for checkout transactions by checkout date

## Duration buckets

Checkout duration uses these fixed buckets:

- `< 8 hours`
- `8 to <24 hours`
- `1 to <3 days`
- `3 to <7 days`
- `7+ days`

## Source of truth

Custody Analytics uses the same custody-accountability calculation as the `Asset Custody / Accountability` report.

Custody history derives from AssetTrack append-only event history.

The holder ID stored on the Issue event is historical evidence. Holder name and organization are current lookups for that stored holder ID.

Historical case or slot labels are not invented when events do not preserve them.

## Printing

Use the browser print command from the dashboard page.

The dashboard uses browser-print styling only. It does not add charts to the custody accountability PDF.
