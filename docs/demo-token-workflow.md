# Demo Token Workflow

## What this is

The demo token is not a login.

It is a simple key that unlocks one action:
sending a sample receipt email.

Nothing else.

---

## What works without a token

Anyone can open `/demo`.

They can:
- view sample data
- see how the system works
- walk through the demo

This is all sample content.  
No real system data is shown.

---

## What the token does

The token controls one thing:

Can the user send a sample receipt email?

If the token is valid:
- the send button appears
- the email can be sent

If the token is missing or invalid:
- the page still loads
- the button is hidden
- sending is blocked

---

## Why this matters

You can share `/demo` freely.

Only people with a token can send a sample receipt.

This keeps the demo safe while still useful.

---

## Where tokens come from

Tokens are created manually and stored in environment variables.

Example:
```
ASSETTRACK_DEMO_TOKENS=TEAM-A.20260418.EXP30
```

There is:
- no database
- no admin screen
- no automatic generation

---

## How expiration works

The token contains its own expiration.

Example:
```
TEAM-A.20260418.EXP30
```

Meaning:
- issued on April 18, 2026
- valid for 30 days

The system checks this locally using UTC.

No external lookup is required.

---

## What happens if the token is invalid

If the token is:
- malformed
- expired
- not configured

Then:
- the send button is not shown
- sending returns 404

There is no partial access.

---

## What happens when a demo email is sent

When the user clicks send:

- a demo email is sent
- it contains sample data only

Important:
- the email address is not saved to the database
- nothing is written to the event log
- no account is created

The system only stores (in session):
- send count
- last send time (for cooldown)

---

## How to add or change a token

Tokens are controlled through environment variables.

### Add a new token

1. Open your environment config (`.env` or deployment settings)
2. Find or create:

```
ASSETTRACK_DEMO_TOKENS=
```

3. Add your token:

```
ASSETTRACK_DEMO_TOKENS=TEAM-A.20260418.EXP30
```

For multiple tokens:

```
ASSETTRACK_DEMO_TOKENS=TEAM-A.20260418.EXP30,TEAM-B.20260418.EXP14
```

---

### Change an existing token

Edit the value directly:

```
ASSETTRACK_DEMO_TOKENS=TEAM-A.20260501.EXP30
```

---

### Remove a token

Delete it from the list:

```
ASSETTRACK_DEMO_TOKENS=TEAM-B.20260418.EXP14
```

---

### Apply the change

After updating the environment:

- restart the app or container

Example:
```
docker compose up -d --build
```

The app reads tokens at startup.

---

### Quick check

After restart:

- open `/demo?token=<your-token>`
- confirm the send button appears

If it does not:
- check for typos
- confirm the token format is correct
- confirm the app was restarted

---

## What to tell someone using the demo

“You can view everything without a token.  
The token only allows you to send a sample receipt.”

---

## What this is not

This is not:
- a login system
- an account system
- access to real data

---

## Limits (by design)

- the demo page is always public
- tokens are manually managed
- tokens can be reused
- there is no per-user tracking

---

## Bottom line

The demo is public.  
The token only enables the email action.  
Submitted data is not stored.