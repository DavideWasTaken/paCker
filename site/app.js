import { AI_ENDPOINT } from './config.js';
import { Stage } from './scene.js';

const $ = id => document.getElementById(id);
const COOLDOWN_MS = 3000;
const MAX_STAGES = 6;

// Suggested orders: the prompt goes to the AI; the request is used directly when the AI is unavailable.
const box = (id, width, length, height, max_weight = 30000, quantity = -1) => ({ id, width, length, height, max_weight, quantity });
const item = (id, width, length, height, weight, quantity, rotation = 'flat') => ({ id, width, length, height, weight, quantity, rotation, diagonal: false });
const SUGGESTIONS = [
  {
    label: 'An online order: books, mugs and a lamp',
    prompt: 'Pack an online order in the fewest cartons: 6 books of 24×17×3 cm (400 g each), 2 mugs of 12×9×10 cm (350 g, any orientation) and a lamp of 20×20×35 cm (1.2 kg). Cartons: 30×20×15, 40×30×25 and 60×40×40 cm.',
    request: { boxes: [box('carton S', 300, 200, 150), box('carton M', 400, 300, 250), box('carton L', 600, 400, 400)],
      items: [item('book', 240, 170, 30, 400, 6), item('mug', 120, 90, 100, 350, 2, 'any'), item('lamp', 200, 200, 350, 1200, 1)] },
  },
  {
    label: 'Heavy tiles, max 25 kg per box',
    prompt: 'I need to ship 8 ceramic tiles of 30×30×2 cm, 9 kg each, in crates of 32×32×20 cm that carry at most 25 kg. How many crates?',
    request: { boxes: [box('crate', 320, 320, 200, 25000)], items: [item('tile', 300, 300, 20, 9000, 8)] },
  },
  {
    label: 'Restock a shelf: 40 mixed parts',
    prompt: 'Restock order of 40 parts: 12 of 10×8×6 cm, 10 of 15×10×5 cm (any orientation), 8 of 6×6×12 cm, 6 of 20×15×10 cm and 4 of 8×4×4 cm. Boxes: 40×30×25 cm (unlimited) and 60×40×40 cm (only 2 left).',
    request: { boxes: [box('box 40', 400, 300, 250), box('box 60', 600, 400, 400, 30000, 2)],
      items: [item('part A', 100, 80, 60, 300, 12), item('part B', 150, 100, 50, 450, 10, 'any'), item('part C', 60, 60, 120, 250, 8),
        item('part D', 200, 150, 100, 900, 6), item('part E', 80, 40, 40, 120, 4)] },
  },
];

class RateLimited extends Error {
  constructor(scope, retry) { super('rate_limited'); this.scope = scope; this.retry = retry; }
}

// ---- Engine (WebAssembly in a worker) ----
const engine = new Worker('./engine-worker.js', { type: 'module' });
const pending = new Map();
let nextId = 1;
engine.onmessage = ({ data }) => {
  const job = pending.get(data.id);
  pending.delete(data.id);
  data.error ? job.reject(new Error(data.error)) : job.resolve(data.result);
};
const runEngine = request => new Promise((resolve, reject) => {
  const id = nextId++;
  pending.set(id, { resolve, reject });
  engine.postMessage({ id, request });
});

// ---- Rendering helpers ----
const escape = s => s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const markdown = s => escape(s.trim()).split(/\n{2,}/).map(p => `<p>${p
  .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\n/g, '<br>')}</p>`).join('');
const scrollDown = () => requestAnimationFrame(() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' }));

function addUser(text) {
  $('chat').classList.remove('empty');
  const el = document.createElement('div');
  el.className = 'msg user';
  el.innerHTML = `<div class="bubble">${escape(text)}</div>`;
  $('thread').append(el);
  scrollDown();
}

function addAssistant() {
  const el = document.createElement('div');
  el.className = 'msg assistant';
  el.innerHTML = '<img class="avatar" src="logo.svg" alt=""><div class="body"><div class="cards"></div><div class="text"><span class="typing"><i></i><i></i><i></i></span></div></div>';
  $('thread').append(el);
  scrollDown();
  return { cards: el.querySelector('.cards'), text: el.querySelector('.text') };
}

const stages = [];
function addCard(turn) {
  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML = `<div class="card-head"><span class="tool">pack_order</span><span class="state">composing the layout…</span></div>
    <div class="stage"><span class="label">searching positions</span></div><div class="stats" hidden></div>
    <details hidden><summary>Request and result JSON</summary><pre></pre></details>`;
  turn.cards.append(card);
  const stage = new Stage(card.querySelector('.stage'));
  stage.compose();
  // A playful counter while the layout is being composed.
  const label = card.querySelector('.label');
  let tested = 0;
  const counter = setInterval(() => {
    if (stage.mode !== 'compose') return clearInterval(counter);
    tested += 37 + Math.floor(Math.random() * 90);
    label.textContent = `trying positions… ${tested.toLocaleString('en')}`;
  }, 70);
  stages.push(stage);
  while (stages.length > MAX_STAGES) stages.shift().dispose();
  scrollDown();
  return { card, stage };
}

function showResult({ card, stage }, request, result) {
  const head = card.querySelector('.state');
  const label = card.querySelector('.label');
  if (result.error) {
    head.textContent = 'invalid order';
    head.style.color = 'var(--danger)';
    label.textContent = result.error;
    stage.clear();
    return;
  }
  stage.show(result);
  const total = result.bins.reduce((n, b) => n + b.items.length, 0) + result.unpacked.length;
  head.textContent = result.status === 'complete' ? 'packed' : 'partly packed';
  label.textContent = `${result.bins.length} box${result.bins.length === 1 ? '' : 'es'} · 3D preview`;
  const stats = card.querySelector('.stats');
  stats.hidden = false;
  stats.innerHTML = [
    ['Boxes', result.bins.length],
    ['Products', `${total - result.unpacked.length} / ${total}`],
    ['Volume used', `${(100 * result.stats.utilization).toFixed(0)}%`],
    ['Engine', `${result.stats.elapsed_ms.toFixed(1)} ms`],
    ...(result.stats.proven_optimal ? [['Fewest boxes', 'proven']] : []),
  ].map(([k, v]) => `<span class="stat">${k} <b>${v}</b></span>`).join('');
  const details = card.querySelector('details');
  details.hidden = false;
  details.querySelector('pre').textContent = JSON.stringify({ request, result }, null, 2);
}

// ---- Packing ----
function toRequest(args) {
  const number = (v, fallback) => (Number.isFinite(+v) && +v > 0 ? +v : fallback);
  const boxes = (args.boxes || []).slice(0, 8).map((b, i) => ({
    id: String(b.id || `box ${i + 1}`).slice(0, 60), width: number(b.width, 300), length: number(b.length, 200), height: number(b.height, 150),
    max_weight: number(b.max_weight, 1e12), quantity: Number.isInteger(b.quantity) && b.quantity >= -1 ? b.quantity : -1,
  }));
  const items = (args.items || []).slice(0, 30).map((p, i) => ({
    id: String(p.id || `product ${i + 1}`).slice(0, 60), width: number(p.width, 100), length: number(p.length, 100), height: number(p.height, 100),
    weight: Number.isFinite(+p.weight) && +p.weight >= 0 ? +p.weight : 0,
    quantity: Math.min(Math.max(parseInt(p.quantity, 10) || 1, 1), 256),
    rotation: ['none', 'flat', 'any'].includes(p.rotation) ? p.rotation : 'flat', diagonal: false,
  }));
  const options = { time_limit_ms: 1500 };
  if (['stable', 'contact', 'full_base'].includes(args.support_mode)) options.support_mode = args.support_mode;
  return { boxes, items, options };
}

function summary(result) {
  if (result.error) return { error: result.error };
  const counts = {};
  for (const u of result.unpacked) counts[u.id] = (counts[u.id] || 0) + 1;
  return {
    status: result.status, box_count: result.bins.length,
    boxes: result.bins.map(b => ({ type: b.type_id, products: b.items.length,
      weight: b.weight, fill: `${(100 * b.items.reduce((v, p) => v + p.width * p.length * p.height, 0) / (b.width * b.length * b.height)).toFixed(0)}%` })),
    not_packed: counts, fewest_boxes_proven: result.stats.proven_optimal, engine_ms: +result.stats.elapsed_ms.toFixed(1),
  };
}

async function pack(turn, request) {
  const view = addCard(turn);
  const minimum = new Promise(r => setTimeout(r, 1600)); // let the composing animation breathe
  let result;
  try {
    result = await runEngine(request);
  } catch (error) {
    result = { error: error.message };
  }
  await minimum;
  showResult(view, request, result);
  return result;
}

function localText(result) {
  if (result.error) return `The order could not be packed: ${result.error}`;
  const s = summary(result);
  const lines = [`Packed in **${s.box_count} box${s.box_count === 1 ? '' : 'es'}** (${s.boxes.map(b => `${b.type} ${b.fill}`).join(', ')}).`];
  const missing = Object.entries(s.not_packed).map(([id, n]) => `${n} × ${id}`);
  if (missing.length) lines.push(`Not packed: ${missing.join(', ')}; there is not enough room, stock or weight capacity.`);
  else if (s.fewest_boxes_proven) lines.push('That is provably the fewest boxes possible.');
  return lines.join(' ');
}

// ---- AI ----
const history = [];
async function callAI(messages) {
  const response = await fetch(`${AI_ENDPOINT.replace(/\/$/, '')}/chat`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages }),
  });
  const data = await response.json().catch(() => ({}));
  if (response.status === 429) throw new RateLimited(data.scope, data.retry_after || 60);
  if (!response.ok || !data.message) throw new Error(data.error || `HTTP ${response.status}`);
  return data.message;
}

async function aiTurn(text, turn) {
  const messages = [...history.slice(-8), { role: 'user', content: text }];
  let message = await callAI(messages);
  if (message.tool_calls?.length) {
    messages.push({ role: 'assistant', content: message.content || '', tool_calls: message.tool_calls.slice(0, 1) });
    const call = message.tool_calls[0];
    let args;
    try { args = JSON.parse(call.function.arguments); } catch { args = {}; }
    const result = await pack(turn, toRequest(args));
    messages.push({ role: 'tool', tool_call_id: call.id, content: JSON.stringify(summary(result)) });
    message = await callAI(messages);
  }
  const answer = (message.content || '').trim() || 'Done: see the layout above.';
  history.push({ role: 'user', content: text }, { role: 'assistant', content: answer });
  return answer;
}

// ---- Conversation ----
let busy = false, last = 0;
function setBusy(value) {
  busy = value;
  $('send').disabled = value;
}

async function send(text, preset) {
  text = text.trim();
  if (!text || busy) return;
  if (Date.now() - last < COOLDOWN_MS) return;
  last = Date.now();
  $('prompt').value = '';
  resize();
  addUser(text);
  setBusy(true);
  const turn = addAssistant();
  let answer, note = '';
  try {
    if (AI_ENDPOINT) {
      try {
        answer = await aiTurn(text, turn);
      } catch (error) {
        const fallback = preset?.request || jsonOrder(text);
        const reason = error instanceof RateLimited
          ? (error.scope === 'visitor' ? 'You reached the demo limit of 6 AI messages per minute.' : 'The demo AI is busy right now.')
          : 'The AI is not reachable right now.';
        if (fallback && !turn.cards.children.length) {
          const result = await pack(turn, fallback);
          answer = localText(result);
          note = `${reason} This suggested order ran directly, without AI.`;
        } else {
          answer = `${reason} Try again in a minute; the suggested orders and JSON orders always run locally.`;
          turn.text.classList.add('note', 'error');
        }
      }
    } else {
      const request = preset?.request || jsonOrder(text);
      if (request) {
        answer = localText(await pack(turn, request));
      } else {
        answer = 'The AI assistant is not connected on this page yet. Pick a suggested order, or paste an order as JSON: `{"boxes": [...], "items": [...]}`.';
        turn.text.classList.add('note');
      }
    }
  } finally {
    turn.text.innerHTML = markdown(answer || '') + (note ? `<p class="note">${escape(note)}</p>` : '');
    setBusy(false);
    scrollDown();
  }
}

function jsonOrder(text) {
  try {
    const value = JSON.parse(text);
    return value && Array.isArray(value.boxes) && Array.isArray(value.items) ? value : null;
  } catch {
    return null;
  }
}

// ---- Composer ----
function resize() {
  const area = $('prompt');
  area.style.height = 'auto';
  area.style.height = `${Math.min(area.scrollHeight, 180)}px`;
}
$('prompt').addEventListener('input', resize);
$('prompt').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    send($('prompt').value);
  }
});
$('composer').addEventListener('submit', event => {
  event.preventDefault();
  send($('prompt').value);
});
for (const suggestion of SUGGESTIONS) {
  const chip = document.createElement('button');
  chip.className = 'chip';
  chip.type = 'button';
  chip.textContent = suggestion.label;
  chip.addEventListener('click', () => send(AI_ENDPOINT ? suggestion.prompt : suggestion.label, suggestion));
  $('suggestions').append(chip);
}
$('mode').textContent = AI_ENDPOINT ? 'AI by Groq, rate limited' : 'AI not connected: suggested and JSON orders run directly';
