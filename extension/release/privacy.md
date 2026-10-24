# Credlet browser extension privacy

Credlet connects to the HTTPS vault server you enter. It has no developer-run
vault service, analytics endpoint, advertising service or crash-report upload.

## Your vault server

Signing in sends your owner email, a password-derived authentication value,
optional vault login authenticator code, random device identifier and client
information to your chosen server. The master password is processed locally.
Vault item contents, including saved passwords, authenticator seeds and passkey
private keys, are encrypted in the client before upload. The server also stores
account and synchronization metadata. Its operator can observe connection
metadata such as your IP address and request timing.

Vault requests go directly to that server with HTTPS certificate validation.
Credlet does not send the vault through a developer-operated proxy. The server's
own operation, logging, backups and privacy policy are controlled by its operator.

## Websites and passkeys

When you choose to fill a matching HTTPS page, Credlet places the selected
username/password or authenticator code in that page's fields. The website and
its scripts can then read those values. Credlet does not submit the form.

When you approve a passkey operation, Credlet processes the requesting site's
origin, relying-party information, challenge and account information. It returns
public registration data or an assertion signature to that site. The private
key stays inside the vault/extension and is not returned to the website. Saved
site addresses and passkey records synchronize as encrypted vault contents.

Credlet uses the current page address for origin checks and explicitly requested
filling. It does not upload the page body, collect browser history, record your
general keystrokes or send browsing activity to an analytics service.

## Local storage and deletion

Extension storage keeps only the server address, owner email and random device
identifier. Master passwords, vault keys, session tokens and decrypted items
remain in process memory. The vault locks after five minutes or when its
background process terminates. This does not promise forensic erasure of browser
or operating-system memory.

Use the vault's item-management and account controls to delete server data.
Removing this extension does not delete the server vault or its backups.

The **Copy** controls write only the value you select to the system clipboard.
Credlet does not read the clipboard. Copied values remain available to your
operating system and other applications after the vault locks; locking does
not clear the clipboard.
Browser installation, signing and update services have their own privacy
policies; this document describes the Credlet extension itself.
