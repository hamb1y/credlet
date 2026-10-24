# Container acceptance in an isolated Linux VM

`tests/compose_acceptance.py` exercises the generated production Compose stack,
including HTTPS, encrypted clients, WebSockets and stopped-stack recovery. It is
restricted to a disposable QEMU VM identified by its SSH key, pinned host key,
QEMU system vendor and `/srv/lockbox-test/.disposable` marker. It does not use the
host Docker socket. Do not adapt its fixture-reset behavior to a real vault.

The full run passed on **2026-10-23**. Its seven acceptance groups and versions
are recorded in `.tools/compose-acceptance/report.json`. Recovery includes a
fresh state directory and a subsequent backup from the restored deployment.

The test environment uses Alpine **3.24.3**, kernel **6.18.58-0-virt**, QEMU
**11.1.2**, Docker Engine **29.9.2** and Compose **5.6.1**. Docker uses its normal
bridge/NAT network, overlayfs, cgroup v2 and seccomp inside the VM. No production
Compose setting is relaxed. The backend is unpublished, capabilities are dropped,
and registration remains closed after owner enrollment.

The hostname is `vault.localhost`. Caddy's normal automatic HTTPS supplies its
internal CA for this local hostname. The test exports that CA explicitly to its
temporary clients and leaves certificate validation enabled. This proves local
trusted HTTPS with the generated Caddyfile; it does not prove public DNS, router
configuration or public ACME certificate issuance.

## VM runtime

On Linux x64 with KVM, Python **3.14** (Zstandard tar support), `bsdtar`, OpenSSH
and compatible dynamic libraries:

```sh
python3 tools/fetch-linux-vm-runtime.py
```

The fetcher verifies all package SHA-256 digests in
`tools/linux-vm-packages.json`, obtained from Arch's official extra repository
metadata. It extracts packages locally, without installing system packages.
Its binaries were tested against glibc **2.44**; other hosts can use a suitable
system QEMU instead. The Alpine virt ISO is pinned to SHA-256
`cdc1bc0efc64d8d611bf3733f54868172a545888dfd726f518bf279bcb0ff1af`,
from Alpine's release metadata. Kernel/initramfs are extracted from that ISO.
Existing VM disks are never created, formatted or changed by the fetcher.

Create a **new** test disk; exclusive creation refuses an existing disk:

```sh
python3 - <<'PY'
from pathlib import Path
with Path('.tools/linux-vm/disk.raw').open('xb') as disk:
    disk.truncate(8 * 1024**3)
PY
```

Run QEMU in a dedicated terminal. The console is the VM's serial terminal;
closing QEMU stops this disposable machine.

```sh
env LD_LIBRARY_PATH=.tools/qemu/root/usr/lib \
  .tools/qemu/root/usr/bin/qemu-system-x86_64 \
  -L .tools/qemu/root/usr/share/qemu \
  -accel kvm -machine q35 -cpu host -smp 2 -m 4096 \
  -kernel .tools/linux-vm/vmlinuz-virt \
  -initrd .tools/linux-vm/initramfs-virt \
  -append 'console=ttyS0 quiet modules=loop,squashfs,sd-mod,usb-storage' \
  -cdrom .tools/alpine/alpine-virt-3.24.3-x86_64.iso \
  -drive file=.tools/linux-vm/disk.raw,format=raw,if=virtio \
  -netdev user,id=net0,hostfwd=tcp:127.0.0.1:22993-:22 \
  -device virtio-net-pci,netdev=net0 -display none -serial stdio -monitor none
```

Log in as `root` at the disposable ISO console. All commands in the next block
are **inside that newly created VM**. Format `/dev/vda` only on the first boot of
the new empty disk; omit `mkfs` on later boots.

```sh
ip link set lo up
ip link set eth0 up
udhcpc -i eth0
printf '%s\n' \
  'https://dl-cdn.alpinelinux.org/alpine/v3.24/main' \
  'https://dl-cdn.alpinelinux.org/alpine/v3.24/community' > /etc/apk/repositories
apk add python3 openssh e2fsprogs iptables ca-certificates
mkfs.ext4 -q -F /dev/vda
mkdir -p /srv/lockbox-test
mount -t ext4 /dev/vda /srv/lockbox-test
printf '%s\n' 'lockbox-disposable-linux-vm' > /srv/lockbox-test/.disposable
rc-service cgroups start
printf '%s\n' '127.0.0.1 vault.localhost' >> /etc/hosts
mkdir -p /root/.ssh /etc/ssh/sshd_config.d
chmod 700 /root/.ssh
printf '%s\n' 'AllowTcpForwarding local' \
  'PermitOpen 127.0.0.1:8222 127.0.0.1:443' > /etc/ssh/sshd_config.d/lockbox-test.conf
```

On the host, create `.tools/linux-vm/id_ed25519` using `ssh-keygen -t ed25519`
with an empty passphrase for this disposable VM only. Paste its `.pub` contents
into the guest's `/root/.ssh/authorized_keys`, mode `600`. Run
`rc-service sshd start` in the guest. Connect once through port **22993**, saving
the inspected guest host key in `.tools/linux-vm/known_hosts` rather than changing
the user's global known-hosts file. Subsequent connections use
`StrictHostKeyChecking=yes` and `IdentitiesOnly=yes`.

Install Docker's official static Linux x86_64 binaries inside the guest's
`/usr/local/bin`, and the Compose plugin at
`/usr/local/lib/docker/cli-plugins/docker-compose`. The acceptance run recorded
the versions above. Start the foreground guest daemon with:

```sh
dockerd --data-root /srv/lockbox-test/docker \
  --pidfile /run/lockbox-docker.pid --log-level warn
```

Copy the project's `lockbox.py` to `/srv/lockbox-test/lockbox.py` in the guest.
The ISO boots into RAM: its packages and SSH setup must be recreated after a
reboot; the mounted test disk retains images, vault data and backups.

## Enroll the disposable owner and run

Use a separate host terminal for an SSH tunnel, with the private key and
known-hosts file described above:

```sh
ssh -N -p 22993 -i .tools/linux-vm/id_ed25519 \
  -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=.tools/linux-vm/known_hosts \
  -L 127.0.0.1:18222:127.0.0.1:8222 \
  -L 127.0.0.1:18443:127.0.0.1:443 root@127.0.0.1
```

In the guest run `python3 /srv/lockbox-test/lockbox.py --state
/srv/lockbox-test/state init --hostname vault.localhost --email owner@example.com`,
then the same command prefix with `enroll`. Register that exact test email at
host `http://127.0.0.1:18222`, using a disposable master password. Use Argon2id
for the test account's KDF. Start production with the same prefix and `up`.
Check that `vault.localhost` resolves to host loopback.

Create `.tools/compose-acceptance/fixture.json` with mode `600`, containing
`server` = `https://vault.localhost:18443`, `email` = `owner@example.com`,
`password` = the disposable master password, and `itemPassword` = a different
random disposable password. Keep this file private; it is ignored by version
control. Supply the official CLI at `.tools/node_modules/.bin/bw` as described
in the project README, then run:

```sh
python3 tests/compose_acceptance.py
```

The test permits only its known fixture item names before resetting records
left by a prior interrupted run. Unknown items cause an immediate refusal.
It checks two isolated official CLI profiles, independent TOTP calculation,
extension/CLI encryption interoperability, headless passkey creation and
independent signature verification, authenticated WSS delivery, absence of the
plaintext item password in server files, full CLI backup/restore, recovered
passkey signing, and deletion sync. Actual browser/Android UI acceptance runs
separately; the headless container passkey check does not replace those tests.

The harness paces sign-ins to respect the unchanged production limit of five
burst logins with a one-minute token refill. It stops both test deployments on
exit and writes `.tools/compose-acceptance/report.json` only after every check
passes. Before repeating, run `up` for the original fixture state in the VM.

The VM and SSH tunnel belong to this test setup. Stop those specific processes
when finished. No host daemon, bridge, sysctl or global trust store is changed.

Primary runtime sources: [Alpine releases](https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/),
[Arch package archive](https://archive.archlinux.org/packages/),
[Docker static installation](https://docs.docker.com/engine/install/binaries/),
[Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https).
