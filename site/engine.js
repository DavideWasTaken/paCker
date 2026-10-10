// Runs the paCker CLI compiled to WebAssembly (wasm32-wasi): the request JSON is
// stdin, the result JSON is stdout. A minimal WASI layer, enough for this program.
const ERRNO = { SUCCESS: 0, BADF: 8, NOENT: 44, SPIPE: 70 };

class Exit {
  constructor(code) { this.code = code; }
}

export async function loadEngine(url) {
  const bytes = await (await fetch(url)).arrayBuffer();
  return WebAssembly.compile(bytes);
}

export async function pack(module, request) {
  const input = new TextEncoder().encode(typeof request === 'string' ? request : JSON.stringify(request));
  const output = [];
  let offset = 0, memory;
  const view = () => new DataView(memory.buffer);
  const bytes = () => new Uint8Array(memory.buffer);
  const iovecs = (iovs, count) => Array.from({ length: count }, (_, i) =>
    [view().getUint32(iovs + 8 * i, true), view().getUint32(iovs + 8 * i + 4, true)]);
  const wasi = {
    args_sizes_get(argc, size) { view().setUint32(argc, 1, true); view().setUint32(size, 7, true); return ERRNO.SUCCESS; },
    args_get(argv, buffer) {
      view().setUint32(argv, buffer, true);
      bytes().set(new TextEncoder().encode('packer\0'), buffer);
      return ERRNO.SUCCESS;
    },
    clock_time_get(id, precision, out) {
      const ns = id === 0 ? BigInt(Date.now()) * 1000000n : BigInt(Math.round(performance.now() * 1e6));
      view().setBigUint64(out, ns, true);
      return ERRNO.SUCCESS;
    },
    fd_read(fd, iovs, count, read) {
      if (fd !== 0) return ERRNO.BADF;
      let total = 0;
      for (const [pointer, length] of iovecs(iovs, count)) {
        const chunk = input.subarray(offset, offset + length);
        bytes().set(chunk, pointer); offset += chunk.length; total += chunk.length;
        if (chunk.length < length) break;
      }
      view().setUint32(read, total, true);
      return ERRNO.SUCCESS;
    },
    fd_write(fd, iovs, count, written) {
      let total = 0;
      for (const [pointer, length] of iovecs(iovs, count)) {
        if (fd === 1) output.push(bytes().slice(pointer, pointer + length));
        total += length;
      }
      view().setUint32(written, total, true);
      return ERRNO.SUCCESS;
    },
    fd_fdstat_get(fd, out) {
      if (fd > 2) return ERRNO.BADF;
      view().setUint8(out, 2); view().setUint16(out + 2, 0, true);
      view().setBigUint64(out + 8, 0xffffffffn, true); view().setBigUint64(out + 16, 0xffffffffn, true);
      return ERRNO.SUCCESS;
    },
    fd_fdstat_set_flags: () => ERRNO.SUCCESS,
    fd_close: () => ERRNO.SUCCESS,
    fd_seek: () => ERRNO.SPIPE,
    fd_prestat_get: () => ERRNO.BADF,
    fd_prestat_dir_name: () => ERRNO.BADF,
    path_open: () => ERRNO.NOENT,
    proc_exit(code) { throw new Exit(code); },
  };
  const instance = await WebAssembly.instantiate(module, { wasi_snapshot_preview1: wasi });
  memory = instance.exports.memory;
  try {
    instance.exports._start();
  } catch (error) {
    if (!(error instanceof Exit)) throw error;
  }
  const text = new TextDecoder().decode(new Uint8Array(output.flatMap(chunk => [...chunk])));
  return JSON.parse(text);
}
