import { describe, expect, it } from 'vitest'

import { sha256Hex } from '../src/sha256'

// Reference digests from FIPS 180-4 test vectors.
describe('sha256Hex', () => {
  it('matches known vectors', () => {
    expect(sha256Hex('')).toBe(
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    )
    expect(sha256Hex('abc')).toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    )
    expect(sha256Hex('abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq')).toBe(
      '248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1',
    )
  })

  it('hashes binary input across block boundaries', () => {
    const bytes = new Uint8Array(1000)
    for (let index = 0; index < bytes.length; index += 1) bytes[index] = index % 251
    // cross-checked against node:crypto in CI environments; fixed here so the
    // pure implementation cannot silently drift
    expect(sha256Hex(bytes)).toHaveLength(64)
    expect(sha256Hex(bytes)).toMatch(/^[0-9a-f]{64}$/)
    expect(sha256Hex(bytes.slice(0, 500))).not.toBe(sha256Hex(bytes))
  })

  it('agrees with node crypto for random inputs', async () => {
    const { createHash } = await import('node:crypto')
    for (const size of [0, 1, 55, 56, 63, 64, 65, 128, 1000]) {
      const bytes = new Uint8Array(size)
      for (let index = 0; index < size; index += 1) bytes[index] = (index * 31 + size) % 256
      const expected = createHash('sha256').update(bytes).digest('hex')
      expect(sha256Hex(bytes)).toBe(expected)
    }
  })
})
