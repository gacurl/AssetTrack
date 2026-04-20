# AssetTrack User Manual

## 1. What AssetTrack Is

**What this does**  
AssetTrack tracks who has each asset. It stages scans first, then commits changes with a receipt and audit record.

**Do this**
1. Use AssetTrack when assets are issued or returned.
2. Scan assets into a queue.
3. Review the preview.
4. Commit only when correct.

**What happens next**  
The system records custody changes and creates a receipt. The scan queue clears after commit.

**Watch for**
- Scanning alone does nothing. You must commit.
- Preview is required before commit.

---

## 2. Logging In

**What this does**  
Logs you into AssetTrack as an active user.

**Do this**
1. Open AssetTrack.
2. Enter your username.
3. Enter your password.
4. Click **Login**.

**What happens next**  
- Valid login → Dashboard  
- Invalid login → Error message  
- Disabled user → Access denied  

**Watch for**
- Too many attempts → temporary lockout  
- Temp password users are forced to change password first  

---

## 3. Logging Out

**What this does**  
Ends your session.

**Do this**
1. Click **Logout** in the top navigation.

**What happens next**  
You return to the login screen.

**Watch for**
- Logging out does not undo committed actions

---

## 4. Password Reset

**What this does**  
Admin creates a temporary password. User must change it before normal use.

**Admin steps**
1. Go to **Users**
2. Click **Generate Temp Password**
3. Copy the password immediately
4. Give it to the user (in person or secure channel)

**User steps**
1. Log in with the temp password
2. You will be forced to change password
3. Enter new password
4. Click **Update Password**

**What happens next**  
- Temp password works once  
- New password replaces it  
- Normal access resumes  

**Watch for**
- Temp password is shown once only  
- Disabled users still cannot log in  

---

## 5. Issue Workflow

**What this does**  
Moves assets from storage to a holder.

**Do this**
1. Click **Issue**
2. Select a holder (if prompted)
3. Set building and room
4. Click **Save current location**
5. Click the scan box
6. Scan asset tag or case barcode
7. Review validation summary
8. Click **Preview / Confirm**
9. Confirm both checkboxes
10. Click **Commit Issue**

**What happens next**  
- Assets move to **IN_CUSTODY**  
- Events are recorded  
- Receipt is created  
- Queue clears  

**Watch for**
- You cannot scan until holder and location are set  
- Only valid assets will commit  

---

## 6. Return Workflow

**What this does**  
Moves assets from a holder back to storage.

**Do this**
1. Click **Return**
2. Click the scan box
3. Scan asset tag or case barcode
4. Review validation summary
5. Click **Preview / Confirm**
6. Confirm both checkboxes
7. Click **Commit Return**

**What happens next**  
- Assets return to **STORAGE**  
- Holder is cleared  
- Receipt is created  
- Queue clears  

**Watch for**
- Asset must be in custody  
- Home slot must be available  

---

## 7. Case Barcode Scanning

**What this does**  
Adds multiple assets at once.

**Do this**
1. Scan a case barcode during Issue or Return

**What happens next**  
- Matching assets are added to the queue  
- Already queued assets are skipped  

**Watch for**
- Empty case → nothing added  
- Ambiguous match → rejected  

---

## 8. Receipts

**What this does**  
Shows what was committed and creates a record.

**Do this**
1. Click **Receipts**
2. Search by asset, holder, or location
3. Open a receipt
4. Review summary sections
5. Click **Download PDF** if needed

**What happens next**  
You see a snapshot of the transaction. PDF download is available.

**Watch for**
- Receipts are created only after commit  
- Search uses stored receipt data  

---

## 9. Sending Email Receipt

**What this does**  
Emails a receipt PDF.

**Do this**
1. Open a receipt
2. Click **Send Receipt Email** (Queued)
3. Or click **Retry Send** (Failed)

**What happens next**  
- Success → status = Sent  
- Failure → status = Failed  

**Watch for**
- Missing email → cannot send  
- “Sent” means handed off, not guaranteed delivery  

---

## 10. Holders

**What this does**  
Defines who can receive assets.

**Do this**
1. Click **Holders**
2. Search for a person or group
3. Click a holder
4. Click **Select for Issue**

**What happens next**  
Holder is stored for the Issue workflow.

**Watch for**
- Only active holders can be selected  

---

## 11. Admin Users

**What this does**  
Manage system users.

**Do this**
1. Click **Users**
2. Create user (username, password, role)
3. Click **Enable / Disable**
4. Click **Set Role**
5. Click **Generate Temp Password**

**What happens next**  
Changes apply immediately.

**Watch for**
- **Active — can log in**  
- **Disabled — cannot log in**  
- Reset does NOT enable a user  

---

## 12. Common Fixes

**What this does**  
Quick answers when something doesn’t work.

**Do this**
- Temp password fails → user may be disabled  
- Cannot scan → set holder + location first  
- No receipt → commit not completed  
- Return blocked → asset not in custody or slot occupied  
- Issue blocked → asset not in storage  
- Email failed → check recipient or SMTP  

**What happens next**  
Fix the condition, then retry the action.

**Watch for**
- Queue is staging only  
- Commit is the actual change  