# Tailscale — everyday use

Tailscale is a private mesh network connecting your devices (mac-mini, MacBook
Air, iPhone, and the prod server `flagleaf-prod` = `100.121.33.2`). It gives you
(1) a location-independent way to reach the server and (2) file transfer between
your own devices. **Keep the menu-bar app running** — that's the only upkeep.

> **Your core workflow does NOT depend on Tailscale.** Editing code, `git`,
> `make handoff`/`pickup`, and `make deploy` all use the public path and are
> unchanged. Tailscale is a convenience/security layer on top.

## Reachability reality (Russia)
From Russian networks the tailnet data-plane is **intermittent** — at setup,
`ssh flagleaf` (tailnet) timed out while `ssh flagleaf-pub` (public) worked. So:
- **Default to the public path; try the tailnet opportunistically.**
- **Taildrop is reliable regardless** (it relays even when peers show "offline").

## 1. SSH aliases (add to `~/.ssh/config` on each Mac)
```
Host flagleaf
    HostName flagleaf-prod
    User newgrain
    IdentityFile ~/.ssh/id_ed25519

Host flagleaf-pub
    HostName 111.88.248.159
    User newgrain
    IdentityFile ~/.ssh/id_ed25519
```
Then: `ssh flagleaf` (tailnet, when up) or `ssh flagleaf-pub` (public, always).
If `flagleaf` won't resolve, use the IP `100.121.33.2` in the HostName.

## 2. Deploy / switch machines — unchanged
`make deploy`, `make handoff`, `make pickup` use the **public IP on purpose**, so
they never depend on the tailnet. Nothing changes here.

## 3. Move a file between your devices (Taildrop)
```bash
tailscale file cp <file> alexeys-macbook-air:     # or mac-mini: / iphone-15-pro-max:
tailscale file get ~/Downloads/                   # run on the receiving device
```
(macOS CLI: if `tailscale` isn't on PATH, it's `/Applications/Tailscale.app/Contents/MacOS/Tailscale`.)

## 4. From your phone
iPhone is on the tailnet. Install an SSH app (Termius / Blink) → host `100.121.33.2`,
user `newgrain`, your key → e.g. tail the bot logs on the go (when the tailnet is up).

## What Tailscale is NOT for
- Not code/context sync → that's `git` + `make handoff`/`pickup`.
- Not Anthropic/Telegram access → that's your VPN. (A Tailscale **exit node** abroad
  could provide that, but none is set up.)

## Reverse it anytime
- Server: `sudo tailscale down && sudo apt-get remove tailscale`
- Macs/phone: quit/uninstall the app.
- Public SSH was never closed, so removing Tailscale changes nothing about access.
