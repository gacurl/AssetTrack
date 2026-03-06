# Project Intent — AssetTrack

## What This Project Is Today

This repository currently contains a **desktop inventory application** written in **Python** using **Tkinter** for the user interface and **SQLite** for local storage.

The application:
- Runs fully offline
- Stores all data locally
- Manages inventory items and hand receipts
- Generates DA Form 2062 PDFs using a calibrated overlay

This system already solves a real problem and works as a standalone tool.

---

## What AssetTrack Is Becoming

**AssetTrack** is the product direction for this repository.

AssetTrack is an **offline-first asset tracking system** designed for environments where:
- Internet access is limited or unavailable
- Actions must be explicit and reviewable
- Records may be inspected long after the fact

AssetTrack is intentionally simple and conservative.

---

## Core Design Goals

AssetTrack is designed to be:

- **Offline-first**  
  No dependency on Wi-Fi, Bluetooth, or cloud services.

- **Explicit**  
  State changes happen only when an operator confirms them.

- **Auditable**  
  Every meaningful action leaves a record that can be reviewed later.

- **Defensible**  
  The system should be easy to explain to supervisors and auditors.

- **Boring on purpose**  
  Predictability is more important than speed or cleverness.

---

## What Is an Asset (Conceptually)

An **asset** is a physical item being tracked by the system.

Examples:
- Laptop
- Tablet
- Phone
- Other serialized equipment

Each asset has:
- A unique identifier (such as a serial number or barcode)
- Basic descriptive information
- A current, known state

---

## States and Why They Matter

An asset always has **one current state**.

Examples of states include:
- Stored
- Issued
- Returned
- In transit
- Pending review

States matter because they answer one clear question:

> “What is the confirmed status of this asset right now?”

The system should prevent illegal or unclear state changes.

---

## Audit and History

AssetTrack is moving toward a model where:

- Changes are recorded as **events**
- Events are **append-only**
- Past actions are never erased or rewritten

This protects:
- Operators (clear record of what was done)
- Supervisors (clear accountability)
- Auditors (traceable history)

---

## Relationship to the Existing Code

The current application already provides:
- Local data storage
- Inventory workflows
- PDF generation
- Operator-driven actions

AssetTrack builds on this foundation by:
- Formalizing asset states
- Making audit behavior explicit
- Supporting offline batch ingest
- Improving separation of concerns over time

This evolution is intentional and incremental.

---

## What This Project Is Not

AssetTrack is not:
- A cloud system
- A real-time tracking platform
- A people-tracking system
- An automatic decision-maker

The system does not guess.
It records what was explicitly done.

---

## Guiding Principle

If a future reader can answer these questions by looking at the system:

- What happened?
- When did it happen?
- Who confirmed it?
- Why was it done?

Then AssetTrack is doing its job.
