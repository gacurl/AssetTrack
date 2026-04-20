# AssetTrack Presentation (40 Minutes)

---

## 0. Opening (3 minutes)

**Say**

> “This started with a simple problem:
> we couldn’t answer one question reliably —  
> *Where is each laptop, and who has it?*”

> “Spreadsheets drift. People rotate. Equipment moves.”

> “AssetTrack solves that with a simple rule:
> **every movement is recorded, and nothing is overwritten.**”

---

## 1. The Problem (5 minutes)

**Say**

> “Here’s what usually happens:
> - assets get issued without a record
> - returns aren’t tracked cleanly
> - people leave, and knowledge leaves with them”

> “At that point, you don’t have a system.
> You have guesses.”

---

## 2. The System Design (5 minutes)

**Say**

> “AssetTrack is built on a few strict rules:”

- Events are **append-only**
- You **stage before commit**
- You **always get a receipt**

> “That means:
> - nothing is silently changed
> - everything is reviewable
> - everything is provable”

---

## 3. Architecture (5 minutes)

**Say**

> “This is not a cloud-dependent system.”

- runs on Docker
- SQLite database
- offline-first
- deployable anywhere

> “You can bring this up on a new machine with no tribal knowledge.”

> “That’s the difference between a project and a system.”

---

## 4. Workflow Model (5 minutes)

**Say**

> “Every action follows the same pattern:”

> **Scan → Review → Commit**

Explain:

- scan = staging
- review = validation
- commit = actual change

> “This prevents mistakes before they happen.”

---

## 5. Live Demo (10–12 minutes)

### Issue Flow

**Say**
> “Let’s issue an asset.”

**Do**
- Issue → select holder → set location → scan

**Say**
> “Nothing has changed yet. We’re staging.”

**Do**
- Preview

**Say**
> “We review before committing.”

**Do**
- Commit

**Say**
> “Now it’s recorded. We have a receipt and an audit trail.”

---

### Receipt

**Say**
> “Every action creates a receipt.”

**Do**
- open receipt
- download PDF

> “This is your proof of what happened.”

---

### Return Flow

**Say**
> “Returns follow the same pattern.”

**Do**
- Return → scan → preview → commit

> “Same rules. No guessing.”

---

### Admin / Security

**Say**
> “Security is simple but strict.”

**Do**
- show Users page

> “We can disable users, change roles, and reset passwords.”

**Do**
- Generate temp password

> “Reset is controlled:
> - temporary password
> - shown once
> - forced change before use”

**Point to status**

> “And disabled means disabled — no shortcuts.”

---

## 6. Real-World Lessons (5 minutes)

**Say**

> “The hardest problems were not code.”

- cloud blocked SMTP
- environment variables misaligned
- provider trust delays

> “Production systems fail at the edges — not in the functions.”

---

## 7. System Maturity (3 minutes)

**Say**

> “At this point, AssetTrack is:”

- deployed
- reproducible
- secure baseline (CI passing, vulnerabilities resolved)
- operator-documented

> “It’s not just working — it’s maintainable.”

---

## 8. Close (2 minutes)

**Say**

> “AssetTrack is built for real environments:
> - limited time
> - imperfect conditions
> - real accountability”

> “It answers one question, reliably:
> *Where is the asset, and who has it?*”

---

## Q&A (buffer time)

Use these if needed:

**Q: What prevents mistakes?**  
→ Preview before commit

**Q: Can records be changed?**  
→ No, append-only

**Q: What if someone forgets their password?**  
→ Admin reset, forced change

**Q: What if the system is offline?**  
→ It still works

---