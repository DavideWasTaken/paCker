# AI proxy for the online demo

The demo page is static. This Cloudflare Worker keeps the Groq API key secret, accepts requests only
from the demo's origin, uses a fixed system prompt, model and tool, and rate limits visitors
(6 AI requests per minute per IP, 25 per minute overall). Groq and Cloudflare free plans need no
payment method: past their limits requests are refused, never billed.

1. Create a free API key at <https://console.groq.com/keys>.
2. Create a free Cloudflare account, then from this directory:

   ```sh
   npx wrangler login
   npx wrangler secret put GROQ_API_KEY      # paste the key when asked
   npx wrangler deploy
   ```

3. Put the printed `https://packer-demo.<account>.workers.dev` URL in `site/config.js` as
   `AI_ENDPOINT` and push. Without it, the demo still runs the suggested and JSON orders locally.

`MODEL` and `ALLOWED_ORIGINS` are plain variables in `wrangler.toml`; the limits are the two
`[[ratelimits]]` blocks.
