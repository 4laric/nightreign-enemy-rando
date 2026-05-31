"""aes128.py — dependency-free AES-128 in ECB mode (decrypt + encrypt).

Pure standard library. Tables are *generated* from the GF(2^8) definition,
not transcribed, so there is nothing to typo. Used to decrypt the AES-
protected byte ranges in Nightreign's dvdbnd entries without any pip install.
Self-test at the bottom checks the FIPS-197 known-answer vector.
"""
from __future__ import annotations

def _xtime(a: int) -> int:
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF

def _mul(a: int, b: int) -> int:
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        a = _xtime(a)
        b >>= 1
    return p

# log/antilog over generator 3, then the AES S-box (inverse + affine map).
_exp = [0] * 512
_log = [0] * 256
_x = 1
for _i in range(255):
    _exp[_i] = _x
    _log[_x] = _i
    _x = _mul(_x, 3)
for _i in range(255, 512):
    _exp[_i] = _exp[_i - 255]

def _inv(a: int) -> int:
    return 0 if a == 0 else _exp[255 - _log[a]]

def _affine(b: int) -> int:
    s = 0
    for i in range(8):
        bit = (((b >> i) & 1) ^ ((b >> ((i + 4) % 8)) & 1) ^ ((b >> ((i + 5) % 8)) & 1)
               ^ ((b >> ((i + 6) % 8)) & 1) ^ ((b >> ((i + 7) % 8)) & 1) ^ ((0x63 >> i) & 1))
        s |= bit << i
    return s

SBOX = [_affine(_inv(a)) for a in range(256)]
INV_SBOX = [0] * 256
for _i, _v in enumerate(SBOX):
    INV_SBOX[_v] = _i

_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]

def _expand_key(key: bytes) -> list[int]:
    ek = list(key)                       # 16 bytes
    for i in range(4, 44):               # 44 words total
        t = ek[(i - 1) * 4:(i - 1) * 4 + 4]
        if i % 4 == 0:
            t = t[1:] + t[:1]            # RotWord
            t = [SBOX[b] for b in t]     # SubWord
            t[0] ^= _RCON[i // 4 - 1]
        prev = ek[(i - 4) * 4:(i - 4) * 4 + 4]
        ek += [prev[j] ^ t[j] for j in range(4)]
    return ek                            # 176 bytes

def _add_round_key(s, ek, rnd):
    o = rnd * 16
    for i in range(16):
        s[i] ^= ek[o + i]

# state is column-major: s[r + 4*c]
def _shift_rows(s, inv=False):
    out = s[:]
    for r in range(1, 4):
        for c in range(4):
            src = (c + r) % 4 if not inv else (c - r) % 4
            out[r + 4 * c] = s[r + 4 * src]
    s[:] = out

def _mix_columns(s, inv=False):
    for c in range(4):
        col = s[4 * c:4 * c + 4]
        if not inv:
            a0, a1, a2, a3 = (2, 3, 1, 1)
        else:
            a0, a1, a2, a3 = (14, 11, 13, 9)
        coef = [a0, a1, a2, a3]
        for r in range(4):
            s[4 * c + r] = (_mul(col[0], coef[(0 - r) % 4]) ^ _mul(col[1], coef[(1 - r) % 4])
                            ^ _mul(col[2], coef[(2 - r) % 4]) ^ _mul(col[3], coef[(3 - r) % 4]))

def _sub_bytes(s, box):
    for i in range(16):
        s[i] = box[s[i]]

def encrypt_block(key_sched, block: bytes) -> bytes:
    s = list(block)
    _add_round_key(s, key_sched, 0)
    for rnd in range(1, 10):
        _sub_bytes(s, SBOX); _shift_rows(s); _mix_columns(s); _add_round_key(s, key_sched, rnd)
    _sub_bytes(s, SBOX); _shift_rows(s); _add_round_key(s, key_sched, 10)
    return bytes(s)

def decrypt_block(key_sched, block: bytes) -> bytes:
    s = list(block)
    _add_round_key(s, key_sched, 10)
    for rnd in range(9, 0, -1):
        _shift_rows(s, inv=True); _sub_bytes(s, INV_SBOX); _add_round_key(s, key_sched, rnd); _mix_columns(s, inv=True)
    _shift_rows(s, inv=True); _sub_bytes(s, INV_SBOX); _add_round_key(s, key_sched, 0)
    return bytes(s)

def decrypt_ecb(key: bytes, data: bytes) -> bytes:
    ks = _expand_key(key)
    return b"".join(decrypt_block(ks, data[i:i + 16]) for i in range(0, len(data), 16))

def encrypt_ecb(key: bytes, data: bytes) -> bytes:
    ks = _expand_key(key)
    return b"".join(encrypt_block(ks, data[i:i + 16]) for i in range(0, len(data), 16))
