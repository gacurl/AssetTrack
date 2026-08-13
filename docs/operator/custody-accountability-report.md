# Asset Custody / Accountability Report

Use this report when operators need a printable custody accountability view from AssetTrack.

## Where to find it

1. Log in.
2. Open `Reports`.
3. Select `Asset Custody / Accountability`.

## Preview

The preview opens in the browser before any PDF is generated.

Use it to review:

- active asset totals
- holder / MA accountability
- asset accountability
- outstanding assets
- exceptions or unresolved records

## PDF

Select `Generate PDF` from the preview page.

Expected result:

- the browser downloads a printable PDF version of the same accountability report

Print the downloaded PDF using the browser or PDF viewer print command.

## How to read it

`Custody duration` is the elapsed time between an Issue event and its matching Return event.

For an outstanding issue, custody duration is measured from the Issue event timestamp to the report generation timestamp.

`OUTSTANDING` means the asset has an Issue event that has not been paired with a later Return event.

An exception or unresolved record means AssetTrack could not safely reconstruct or confirm custody from the event history and current reconciliation data. Review the listed asset before treating the report as complete.

## Historical evidence

Custody history derives from AssetTrack append-only event history.

The holder ID stored on the Issue event is historical evidence.

Holder name and organization are current lookups for that stored holder ID, not historical snapshots.

Historical case or slot labels are not invented when events do not preserve them. Storage evidence may show current slot or building-room information when available.
