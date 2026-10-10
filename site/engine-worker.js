// Runs the WebAssembly engine off the main thread so the page stays smooth.
import { loadEngine, pack } from './engine.js';

const ready = loadEngine('./packer.wasm');
self.onmessage = async ({ data }) => {
  try {
    self.postMessage({ id: data.id, result: await pack(await ready, data.request) });
  } catch (error) {
    self.postMessage({ id: data.id, error: String(error?.message || error) });
  }
};
