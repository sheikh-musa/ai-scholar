# Bayan egress-reroute — scope (op#10339 / #15724 follow-up)

**Status:** SCOPING — deeper fix for the recurring getUpdates black-hole. Likely needs
operator/SRE (a network/infra change, not just bot code). Filed by cc-scholar.

## Problem (established, op#10339)

The Studio→Telegram path (`api.telegram.org` → `149.154.166.110:443`) intermittently
**black-holes idle long-poll connections**: TCP stays ESTABLISHED locally but no bytes
return, so `getUpdates` hangs until the SIGALRM backstop. Short requests (getMe) are
unaffected; only the held-open long-poll is. Same SG-network/NAT flakiness class that
hit the console relay + SSL earlier the same night. Frequency is variable (2h clean
after keepalive, then 2 wedges in 15 min) → it tracks the underlying network, not the bot.

**Already mitigated in-bot** (commit 8674bbe + long_poll 15→10): TCP keepalive, shorter
long-poll/deadline, exponential backoff, and a self-healing watchdog. These reduce
frequency + impact and keep continuity, but they do **not** remove the root network flaw.

## Options to route Bayan's Telegram egress off the flaky path

Ranked by effort/blast-radius (cheapest, most-targeted first):

1. **Webhook instead of long-poll (RECOMMENDED real fix).** Telegram *pushes* updates to
   a public HTTPS endpoint → **no idle outbound long-poll to black-hole at all** — it
   removes the failure mode rather than routing around it. Needs public ingress; we already
   have cloudflared/ngrok experience from the fleet-console work, so a cloudflared tunnel →
   a tiny local webhook receiver in mizan_bot is viable. Cost: a receiver endpoint + tunnel;
   moderate code change (swap the poll loop for a webhook handler). Best long-term.
2. **SOCKS5/HTTP proxy for ONLY the bot's Telegram calls.** Stand up a small proxy on a
   stable cloud VPS (healthy egress) and route just `api.telegram.org` through it (urllib
   supports proxies); Supabase + the local encoder calls stay direct. Most targeted
   work-around — minimal blast radius, keeps long-poll. Cost: one small VPS + proxy.
3. **Tailscale exit node.** Tailscale is already present (services bind 100.104.36.27).
   Route Studio egress via an exit node in a healthier region (`tailscale up --exit-node`).
   Cost: a cloud VM as exit node; affects ALL Studio egress (broader than #2).
4. **Local Studio network change (cheapest if it's the LAN).** Wired vs wifi, a different
   router/ISP, or a different DNS/route. If the black-hole is a local NAT/router idle-timeout,
   this could fix it with zero cloud cost. Operator physical check.

## Recommendation

- **Now:** long_poll=10 + keepalive + auto-heal are live (this commit) — continuity holds.
- **Next, cheap probe:** operator checks the Studio's local network path (#4) — if it's a
  router/wifi idle-drop, that's a free fix.
- **If it persists / for durability:** do the **webhook** cutover (#1) — it eliminates the
  idle-long-poll failure mode entirely. Fallback if public ingress is unwanted: the
  targeted SOCKS proxy (#2).

## Needs operator/SRE

Options 1–4 all require infra I cannot provision headless (public tunnel, cloud VPS,
Tailscale exit node, or a physical network change). cc-scholar can implement the **bot-side**
of the webhook cutover (#1) or the proxy wiring (#2) once the infra endpoint exists. Flagging
for operator/SRE to pick the path.
