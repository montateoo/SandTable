# OctoPrint-GoogleHome

Exposes the SandTable as a Google Smart Home device, so a Google Home/Nest Mini can ask what it's
doing and tell it to stop/skip the current pattern.

## What this actually does (read before setting up Google's side)

Google's Smart Home Actions framework has no "arbitrary free-text spoken answer" trait. It only
supports structured **traits** where Google speaks its *own* canned phrasing around values *you*
define. In practice that means:

- **Asking what it's doing**: you'll ask something like *"Hey Google, what mode is [device name]
  in?"* (Google's own phrasing for the `Modes` trait — you don't control the exact wording), and
  Google will answer with one of: `riposo` (idle), `pulizia` (erasing), `disegno` (drawing a
  pattern), or `gara` (an F1 circuit/race is being tracked). It will **not** name which F1 circuit
  specifically — that would require declaring every possible circuit as a fixed mode value ahead of
  time, which doesn't scale across a season. This is a deliberate simplification, not a bug.
- **"Salta questo disegno" (skip)**: set up as a Google Home **Routine** with that literal phrase as
  the trigger, mapped to a "stop" command on this device — Routines let *you* pick the exact trigger
  phrase, separate from Google's own QUERY phrasing above. See step 6.

## Setup

### 1. Generate a static token

This plugin is single-household — there's no real per-user login. Generate any long random string
yourself (e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`) and save it; you'll
enter it in this plugin's settings as **Static access token** in step 5.

### 2. Public endpoint (tunnel)

Google's cloud needs to reach this Pi over the public internet. Run `cloudflared` as a tunnel
pointed at OctoPrint (port 80/5000 depending on your setup). A **named tunnel with a stable
hostname** is strongly preferred over the ephemeral `trycloudflare.com` quick-tunnel mode — an
ephemeral hostname changes on every restart, which breaks the URLs registered with Google in step 3
until you update them. A named tunnel needs a domain in a free Cloudflare account; if you don't have
one, decide this before continuing (see https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/).

Whatever the resulting public hostname is, call it `PUBLIC_HOST` below.

### 3. Google Actions Console project

1. Create a project at https://console.actions.google.com/ → Smart Home.
2. Under **Account linking**, set:
   - Authorization URL: `https://PUBLIC_HOST/plugin/googlehome/oauth2/authorize`
   - Token URL: `https://PUBLIC_HOST/plugin/googlehome/oauth2/token`
   - Generate a **Client ID** and **Client secret** here — these are *separate* from the static
     token in step 1; copy both.
3. Under **Actions** → fulfillment URL, set: `https://PUBLIC_HOST/plugin/googlehome/smarthome`

(Confirm the exact `/plugin/googlehome/...` path prefix against your installed OctoPrint version's
`BlueprintPlugin` routing before pasting these in — it's the standard prefix, but verify once.)

### 4. Keep the Action in testing/draft mode

For personal use you do **not** need to submit for review — testing mode works indefinitely for
accounts you add as testers in the Actions Console, which is all that's needed here.

### 5. Configure this plugin

OctoPrint → Settings → Google Home: paste the Client ID, Client secret (from step 3), the static
token (from step 1), and set the device name you'll use by voice (default "Tavolo").

### 6. Link your account + set up the skip Routine

1. Google Home app → Add device → Works with Google → find your Action → it'll hit
   `/oauth2/authorize`, which auto-approves (single-household, no login form) → device should appear.
2. Google Home app → Routines → New Routine → "When this is said": type `salta questo disegno`
   exactly. Then "And also": add an action on your new device — choose **stop**. This is what
   actually triggers `sandtable`'s skip.

### 7. Test

- `curl` the `/smarthome` route directly first (see the plan's test plan) before involving Google at
  all — isolates plugin bugs from anything Google/OAuth/tunnel related.
- Then the voice tests: ask "Hey Google, what mode is [device name] in" while something is actually
  running, and say "salta questo disegno" while a SandTable pattern is printing.
