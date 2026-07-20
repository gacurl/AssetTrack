# Local Admin Account Recovery

Issue: 29-15

Classification: Class 4 - Security / Authentication

This policy defines the approved local-only procedure for restoring access to
an existing primary AssetTrack admin account when that account is inactive or
its password is unavailable.

## Security boundary

This is not a web password recovery feature.

Do not add:

- a public recovery route
- a hidden admin account
- a hard-coded password
- a role-promotion path
- a stored password hash display
- a cloud or external identity dependency

The executable recovery artifact is not stored in this repository. The
authorized system owner stores it separately and runs it locally only when
needed.

## Approved recovery behavior

The local recovery procedure may:

- target an explicitly named existing account, normally `admin`
- verify the account exists
- verify the account already has the `admin` role
- reactivate that admin account when inactive
- reset its password through AssetTrack's existing temporary-password behavior
- print the generated temporary password once
- require the normal forced password-change flow on next login

The procedure must fail safely when:

- the named account does not exist
- the named account is not already an admin
- database access fails
- any assumption is not met

The procedure must not create, modify, or delete custody events, audit history,
assets, holders, receipts, slots, or operational data.

## Why this is needed

AssetTrack already protects against disabling or demoting the last active
admin. That guard works as designed.

The observed lockout condition came from active smoke-test admin accounts that
remained in the development database. Because more than one active admin
existed, the primary `admin` account could be disabled without triggering the
last-active-admin safeguard. The operator then did not know the generated
passwords for those remaining smoke-test admin accounts.

Root cause: admin access still existed in the database, but no known local
credential was available to use it.

## Procedure

1. Work on the local machine that owns the AssetTrack deployment.
2. Stop public access to the app if the machine is reachable by others.
3. Confirm the target username, normally `admin`.
4. Run the separately stored recovery script against the existing Docker
   deployment.
5. Confirm the script reports the target account exists and is already an
   admin.
6. Copy the printed temporary password immediately. It is shown once.
7. Log in as the target admin with the temporary password.
8. Complete the forced password-change flow.
9. Store the new password through the approved local channel.
10. Resume normal operation.

## Expected result

- the target admin account is active
- the old password no longer works
- the temporary password works only until changed
- the admin is forced to change password before normal app use
- normal role enforcement remains active
- no custody, receipt, event, audit, schema, or persistence behavior changes

## Smoke-test admin cleanup follow-up

Do not fold smoke-test account cleanup into account recovery.

Recommended separate issue: define a development-database cleanup procedure for
manual smoke-test admin accounts.

Smallest safe scope:

- inventory known smoke-test admin usernames in local development data
- confirm they are not operational accounts
- disable or remove only approved development-only accounts
- preserve at least one known active admin
- document when cleanup is safe to run
