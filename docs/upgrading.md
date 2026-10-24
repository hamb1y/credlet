# Upgrading to Credlet

Credlet is the new name for Lockbox. Version 0.2.0 keeps the same vault format,
owner account, encryption and server compatibility. You do not need to export
or recreate your passwords or passkeys.

## Server

Keep your existing state directory. The default directory sits beside the
management tool, so moving the new tool does not move the vault automatically.
Use `--state` to point it at the existing directory:

```sh
python3 credlet.py --state /absolute/path/to/existing/state down
python3 credlet.py --state /absolute/path/to/existing/state backup
python3 credlet.py --state /absolute/path/to/existing/state render
python3 credlet.py --state /absolute/path/to/existing/state up
python3 credlet.py --state /absolute/path/to/existing/state check
```

For the packaged tool, substitute `./credlet-server` on Linux or
`.\credlet-server.exe` on Windows. Stop the service and keep a verified,
private backup before replacing binaries. Backups themselves are not encrypted.

Existing deployments retain their `lockbox` / `lockbox-enroll` Docker Compose
project names. New deployments use `credlet` / `credlet-enroll`. The manager
checks both names before backup or restore, preventing two deployments from
writing the same SQLite database. Backups made with Lockbox remain restorable.

## Desktop companion

Quit the old application before opening Credlet. The companion reuses existing
Lockbox preferences when no Credlet preferences exist, including the server,
email and device identifier. No password or session key is stored in those
preferences. `CREDLET_CONFIG_DIR` selects an explicit settings directory;
`LOCKBOX_CONFIG_DIR` is still accepted for existing launch scripts.

Saved `lockbox-app://` application links continue to work. New links use
`credlet-app://`; linking an existing application again does not duplicate it.
The captured application must still have the same executable identity.

## Browser extensions

The Firefox display name changes to Credlet; its permanent add-on ID remains
`lockbox@selfhost.local` so preferences and future updates keep their identity.
The release XPI remains explicitly unsigned unless Mozilla signing is configured.

For Chrome's unpacked extension, replace the files inside the same installed
folder and click **Reload** in `chrome://extensions`. Loading a new folder can
create a different extension identity; simply sign in again if that happens.

Client sessions start locked after an update. Sign in with your existing server,
email and master password. For rollback, use the prior release with the same
state directory; this release does not migrate the vault database schema.
