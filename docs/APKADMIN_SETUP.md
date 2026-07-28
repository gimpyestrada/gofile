# Apkadmin Setup

Apkadmin has no public API and sits behind Cloudflare, so the uploader
authenticates with cookies copied from a browser session. Cloudflare challenges
cannot be solved programmatically, which is why this host needs manual setup
while the other three only need an API key.

You need three values in `config.json`:

| Key | What it is |
| --- | --- |
| `apkadmin_cf_clearance` | Proof that your browser passed the Cloudflare challenge |
| `apkadmin_xfss` | Your logged-in Apkadmin session |
| `apkadmin_user_agent` | The browser User-Agent that solved the challenge |

## Getting the values

1. Open <https://apkadmin.com> in your browser and log in. Wait for any
   "Checking your browser" screen to finish.
2. Open developer tools with `F12` and select the **Application** tab
   (**Storage** in Firefox).
3. Expand **Cookies** in the left sidebar and select `https://apkadmin.com`.
4. Copy the **Value** of the `cf_clearance` cookie into `apkadmin_cf_clearance`.
5. Copy the **Value** of the `xfss` cookie into `apkadmin_xfss`.
6. Switch to the **Console** tab, run `navigator.userAgent`, and copy the
   result (without the surrounding quotes) into `apkadmin_user_agent`.
7. Set `"apkadmin_enabled": true`.

Restart the uploader. The Apkadmin log column should show "Connected to
Apkadmin".

## Why the User-Agent must match

Cloudflare binds `cf_clearance` to the exact browser that solved the challenge.
Sending the cookie with a different User-Agent invalidates it, and the uploader
gets a challenge page instead of the upload form. Copy the string exactly — a
version-number difference is enough to break it.

## When it stops working

`cf_clearance` expires regularly (often within a day), and `xfss` expires when
your Apkadmin session ends. The uploader detects this at startup and reports:

```
Auth error: Cloudflare challenge detected — cf_clearance cookie is expired
or the User-Agent does not match.
```

Repeat the steps above to refresh both cookies. If you have also upgraded your
browser since the last time, re-copy the User-Agent too.

## Troubleshooting

**"Upload form not found in page response"** — usually a stale `xfss` cookie, so
you are being served the logged-out page. Log in again and re-copy `xfss`. If
both cookies are fresh, the site layout may have changed and the scraper in
[apkadmin_api.py](../apkadmin_api.py) needs updating.

**Works, then fails partway through a batch** — a cookie expired mid-run.
Refresh both cookies and retry the remaining files.

**Nothing appears in the Apkadmin column** — `apkadmin_enabled` is still
`false`, or the host is disabled in the settings menu (⚙️).

## A note on these credentials

`xfss` is a live session cookie: anyone holding it can act as you on Apkadmin.
It is stored in plaintext in `config.json`, so keep that file out of version
control — the repository's `.gitignore` already excludes it — and do not paste
these values into bug reports.
