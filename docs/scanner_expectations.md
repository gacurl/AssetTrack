<!-- docs/scanner_expectations.md -->

# Scanner expectations (OPN-2004)

This document explains, in plain terms, how the scanner is expected to behave, how AssetTrack listens to it, and how to tell whether a problem is the scanner or the software.

The short version:  
AssetTrack does not “talk” to the scanner directly. It listens to whatever the scanner types, the same way it would listen to a keyboard.

---

## How the scanner works (conceptually)

Think of the scanner as a very fast keyboard.

- You pull the trigger.
- The scanner types characters.
- It finishes by pressing Enter.

AssetTrack waits for that Enter key. When it sees it, it treats everything before it as **one scan**.

---

## What AssetTrack expects

AssetTrack expects three simple things:

- The scanner sends text like a keyboard (USB HID mode).
- One scan equals one line of text.
- Each scan ends with Enter.

If those three things are true, AssetTrack will behave correctly.

---

## What you should see as an operator

A normal scan looks like this:

- You scan a barcode.
- One value appears in the intake field.
- That value is added to the queue **once**.

Nothing more. Nothing less.

---

## How to tell where a problem lives

Before assuming the software is broken, always answer this question:

**Does the scanner behave the same way in a plain text app?**

Open Notes, TextEdit, or Notepad and scan there first.

That one test tells you a lot.

---

## Common problems and what they usually mean

### Nothing shows up when you scan

This is almost always a scanner or cable issue.

Things to check:
- Is the scanner charged or powered?
- Is the USB cable firmly connected?
- Try a different USB port.
- Scan into a plain text app to confirm it’s sending keystrokes at all.

If nothing appears anywhere, AssetTrack is not the problem.

---

### One trigger creates two entries

This usually means the scanner is sending Enter twice.

Try this first:
- Slow down slightly between scans.
- Scan into a plain text app and watch what happens.

If you see two lines appear from one trigger pull, that’s a scanner configuration issue.

AssetTrack is just listening to what it’s given.

---

### Weird characters or partial scans

This is usually a hardware or configuration problem.

Things to try:
- Replace the USB cable (cheap cables fail often).
- Scan into a plain text app and inspect the output.
- If the output is messy everywhere, the scanner config is wrong.
- If it’s clean everywhere except AssetTrack, capture an example and report it.

---

### Wrong barcode, wrong length, or wrong value

This is almost always a process issue.

- Confirm you’re scanning the correct label type.
- Don’t mix asset tags, serial numbers, and shipping labels.
- If multiple label types exist at your site, pick one standard and stick to it.

Consistency matters more than perfection.

---

## Operator sanity checklist

Before escalating a problem:

- Scan into a plain text app.
- Try a known-good barcode.
- Swap the USB cable if behavior is odd.
- If the scanner output is wrong everywhere, fix the scanner first.

If it’s clean everywhere except AssetTrack, that’s when it’s worth filing an issue.

---

The goal here isn’t blame — it’s fast diagnosis.  
Five minutes of isolation beats an hour of guessing.