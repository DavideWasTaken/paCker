// paCker demo proxy: keeps the Groq key secret and rate limits visitors.
import { DurableObject } from 'cloudflare:workers';

// Only the demo's own conversation shape is forwarded, with a fixed system prompt,
// model and tool list, so the endpoint cannot be used as a general free LLM API.
const GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions';
const MAX_MESSAGES = 16;
const MAX_TEXT = 4000;
const MAX_TOOL_RESULT = 12000;
const MAX_BODY = 64 * 1024;
const MINUTE = 60 * 1000, DAY = 24 * 60 * MINUTE;
const VISITOR_RULES = [{ limit: 6, window: MINUTE }, { limit: 40, window: DAY }];
const GLOBAL_RULES = [{ limit: 15, window: MINUTE }, { limit: 700, window: DAY }];

// Exact sliding-window counter: one object per visitor IP, one for the whole demo.
export class Limiter extends DurableObject {
  async hit(rules) {
    const now = Date.now(), longest = Math.max(...rules.map(r => r.window));
    const hits = ((await this.ctx.storage.get('hits')) || []).filter(t => now - t < longest);
    for (const rule of rules) {
      const recent = hits.filter(t => now - t < rule.window);
      if (recent.length >= rule.limit) {
        await this.ctx.storage.put('hits', hits);
        return { ok: false, retry_after: Math.ceil((recent[0] + rule.window - now) / 1000), window: rule.window };
      }
    }
    hits.push(now);
    await this.ctx.storage.put('hits', hits);
    return { ok: true };
  }
}

const limiter = (env, name) => env.LIMITER.get(env.LIMITER.idFromName(name));

const SYSTEM = `You are the assistant of the paCker demo. paCker is a fast 3D box packing engine.
The user describes boxes and products in natural language. Turn the description into one call of the
pack_order tool. Use millimetres and grams. If the user gives no boxes, invent two or three sensible
carton sizes. If quantities or sizes are missing, choose plausible values and say so briefly.
Rotation: "flat" keeps the height (default), "any" lets a product lie on any face, "none" forbids
rotation. Leave support_mode at its default ("stable") unless the user asks otherwise.
After the tool result, answer in the user's language in at most four short sentences: boxes used,
anything not packed and why, and one useful observation. Never invent results; only report the tool
output. Politely decline requests unrelated to packing.`;

const TOOLS = [{
  type: 'function',
  function: {
    name: 'pack_order',
    description: 'Pack products into boxes with the paCker engine and return the layout summary.',
    parameters: {
      type: 'object',
      properties: {
        boxes: {
          type: 'array', minItems: 1, maxItems: 8,
          items: {
            type: 'object',
            properties: {
              id: { type: 'string' }, width: { type: 'number' }, length: { type: 'number' },
              height: { type: 'number' }, max_weight: { type: 'number' },
              quantity: { type: 'integer', description: '-1 for unlimited stock' },
            },
            required: ['id', 'width', 'length', 'height'],
          },
        },
        items: {
          type: 'array', minItems: 1, maxItems: 30,
          items: {
            type: 'object',
            properties: {
              id: { type: 'string' }, width: { type: 'number' }, length: { type: 'number' },
              height: { type: 'number' }, weight: { type: 'number' }, quantity: { type: 'integer' },
              rotation: { type: 'string', enum: ['none', 'flat', 'any'] },
            },
            required: ['id', 'width', 'length', 'height'],
          },
        },
        support_mode: { type: 'string', enum: ['stable', 'contact', 'full_base'] },
      },
      required: ['boxes', 'items'],
    },
  },
}];

function cors(origin) {
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
    Vary: 'Origin',
  };
}

function reply(body, status, origin) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'Content-Type': 'application/json', ...cors(origin) },
  });
}

function text(value, limit) {
  return typeof value === 'string' && value.length <= limit;
}

// Accept only the turns the demo client produces.
function clean(messages) {
  if (!Array.isArray(messages) || !messages.length || messages.length > MAX_MESSAGES) return null;
  const out = [];
  for (const m of messages) {
    if (!m || typeof m !== 'object') return null;
    if (m.role === 'user' && text(m.content, MAX_TEXT)) {
      out.push({ role: 'user', content: m.content });
    } else if (m.role === 'assistant') {
      const calls = Array.isArray(m.tool_calls) ? m.tool_calls : [];
      if (calls.length > 2 || !(m.content == null || text(m.content, MAX_TEXT))) return null;
      for (const c of calls) {
        if (c?.type !== 'function' || c.function?.name !== 'pack_order' || !text(c.id, 100) ||
            !text(c.function.arguments, MAX_TOOL_RESULT)) return null;
      }
      out.push({ role: 'assistant', content: m.content ?? '', ...(calls.length ? { tool_calls: calls.map(c => ({
        id: c.id, type: 'function', function: { name: 'pack_order', arguments: c.function.arguments } })) } : {}) });
    } else if (m.role === 'tool' && text(m.tool_call_id, 100) && text(m.content, MAX_TOOL_RESULT)) {
      out.push({ role: 'tool', tool_call_id: m.tool_call_id, content: m.content });
    } else {
      return null;
    }
  }
  return out;
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin') || '';
    const allowed = (env.ALLOWED_ORIGINS || '').split(',').map(s => s.trim()).filter(Boolean);
    const permitted = allowed.includes(origin) ? origin : allowed[0] || '';
    const { pathname } = new URL(request.url);
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors(permitted) });
    if (request.method !== 'POST' || pathname !== '/chat') return reply({ error: 'not_found' }, 404, permitted);
    if (!allowed.includes(origin)) return reply({ error: 'forbidden_origin' }, 403, permitted);

    const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
    const visitor = await limiter(env, `ip:${ip}`).hit(VISITOR_RULES);
    if (!visitor.ok) return reply({ error: 'rate_limited', scope: visitor.window === DAY ? 'visitor_day' : 'visitor', retry_after: visitor.retry_after }, 429, origin);
    const overall = await limiter(env, 'global').hit(GLOBAL_RULES);
    if (!overall.ok) return reply({ error: 'rate_limited', scope: 'global', retry_after: overall.retry_after }, 429, origin);
    if (Number(request.headers.get('Content-Length') || 0) > MAX_BODY) return reply({ error: 'too_large' }, 413, origin);

    let messages;
    try { messages = clean((await request.json()).messages); } catch { messages = null; }
    if (!messages) return reply({ error: 'invalid_request' }, 400, origin);

    const upstream = await fetch(GROQ_URL, {
      method: 'POST',
      headers: { Authorization: `Bearer ${env.GROQ_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: env.MODEL, messages: [{ role: 'system', content: SYSTEM }, ...messages],
        tools: TOOLS, tool_choice: 'auto', temperature: 0.2, max_completion_tokens: 1500,
      }),
    });
    if (upstream.status === 429) return reply({ error: 'rate_limited', scope: 'provider', retry_after: 60 }, 429, origin);
    if (!upstream.ok) return reply({ error: 'upstream', status: upstream.status }, 502, origin);
    const data = await upstream.json();
    const message = data.choices?.[0]?.message;
    if (!message) return reply({ error: 'upstream' }, 502, origin);
    return reply({ message: { role: 'assistant', content: message.content ?? '', tool_calls: message.tool_calls ?? undefined } }, 200, origin);
  },
};
