// Cloudflare Worker — Telegram Bot API relay for Flagleaf.
//
// WHY: Roskomnadzor IP-blocks Telegram's API from Russian networks, so the
// bot (on a Yandex Cloud RU VM) cannot reach api.telegram.org directly.
// Cloudflare's edge IS reachable from RU and is impractical to block
// wholesale. This Worker sits on Cloudflare and forwards the bot's Telegram
// traffic, so the RU VM only ever talks to Cloudflare.
//
// FLOW: bot → https://<worker>.workers.dev/bot<TOKEN>/<method>
//            → (this Worker) → https://api.telegram.org/bot<TOKEN>/<method>
// Photo downloads use the same host (/file/bot<TOKEN>/<path>), so they're
// covered too.
//
// OPTIONAL HARDENING: in the Worker dashboard, add a Variable named
// ALLOWED_TOKEN set to your bot token. The Worker then refuses any path that
// doesn't carry that token, so it can't be abused as an open Telegram proxy.

const TELEGRAM = "https://api.telegram.org";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Only proxy real Telegram Bot API URL shapes.
    const isApi = path.startsWith("/bot");
    const isFile = path.startsWith("/file/bot");
    if (!isApi && !isFile) {
      return new Response("Flagleaf Telegram relay — not a Telegram API path.", {
        status: 404,
      });
    }

    // Optional allowlist: only forward requests carrying our bot token.
    if (env && env.ALLOWED_TOKEN) {
      if (!path.includes("/bot" + env.ALLOWED_TOKEN + "/")) {
        return new Response("Forbidden", { status: 403 });
      }
    }

    // Forward to Telegram. Drop the inbound Host header so Cloudflare sets
    // Host: api.telegram.org from the target URL.
    const headers = new Headers(request.headers);
    headers.delete("host");

    const target = TELEGRAM + path + url.search;
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body:
        request.method === "GET" || request.method === "HEAD"
          ? undefined
          : request.body,
    });

    // Stream Telegram's response straight back to the bot.
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: upstream.headers,
    });
  },
};
