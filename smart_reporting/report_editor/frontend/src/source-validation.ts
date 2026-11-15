// 浏览器内计算文件字节的 SHA-256，用于保存/导出时核对 Office 草稿身份；
// 非安全上下文（无 crypto.subtle）时回退到纯 JS 实现。
const SHA256_K = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]
const rotr = (value: number, bits: number) => (value >>> bits) | (value << (32 - bits))

function sha256Fallback(input: Uint8Array): Uint8Array {
  const bitLength = input.length * 8
  const paddedLength = Math.ceil((input.length + 9) / 64) * 64
  const data = new Uint8Array(paddedLength)
  data.set(input); data[input.length] = 0x80
  const view = new DataView(data.buffer)
  view.setUint32(paddedLength - 4, bitLength, false)
  let [a, b, c, d, e, f, g, h] = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]
  for (let offset = 0; offset < data.length; offset += 64) {
    const w = new Uint32Array(64)
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(offset + i * 4, false)
    for (let i = 16; i < 64; i++) {
      const x = w[i - 15], y = w[i - 2]
      const s0 = rotr(x, 7) ^ rotr(x, 18) ^ (x >>> 3)
      const s1 = rotr(y, 17) ^ rotr(y, 19) ^ (y >>> 10)
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0
    }
    let [aa, bb, cc, dd, ee, ff, gg, hh] = [a, b, c, d, e, f, g, h]
    for (let i = 0; i < 64; i++) {
      const s1 = rotr(ee, 6) ^ rotr(ee, 11) ^ rotr(ee, 25)
      const ch = (ee & ff) ^ (~ee & gg)
      const t1 = (hh + s1 + ch + SHA256_K[i] + w[i]) >>> 0
      const s0 = rotr(aa, 2) ^ rotr(aa, 13) ^ rotr(aa, 22)
      const maj = (aa & bb) ^ (aa & cc) ^ (bb & cc)
      const t2 = (s0 + maj) >>> 0
      ;[hh, gg, ff, ee, dd, cc, bb, aa] = [gg, ff, ee, (dd + t1) >>> 0, cc, bb, aa, (t1 + t2) >>> 0]
    }
    a = (a + aa) >>> 0; b = (b + bb) >>> 0; c = (c + cc) >>> 0; d = (d + dd) >>> 0
    e = (e + ee) >>> 0; f = (f + ff) >>> 0; g = (g + gg) >>> 0; h = (h + hh) >>> 0
  }
  const result = new Uint8Array(32), words = [a, b, c, d, e, f, g, h]
  words.forEach((word, i) => { result.set([(word >>> 24) & 255, (word >>> 16) & 255, (word >>> 8) & 255, word & 255], i * 4) })
  return result
}

export async function bytesSha256(input: Uint8Array<ArrayBuffer>): Promise<string> {
  const digest = crypto.subtle
    ? new Uint8Array(await crypto.subtle.digest('SHA-256', input))
    : sha256Fallback(input)
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('')
}
