#!/usr/bin/env python3
"""Known-answer + round-trip tests for the dependency-free AES-128 (aes128.py).

This module decrypts the AES-protected byte ranges of Nightreign's dvdbnd
entries, so a silent table/key-schedule bug corrupts archive reads. Lock it
to the FIPS-197 reference vectors and structural invariants.

Pure stdlib — always runs, no game data, no pip deps.
"""

import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import aes128  # noqa: E402


# FIPS-197 Appendix C.1 (AES-128) known-answer vector.
KAT_KEY = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
KAT_PLAIN = bytes.fromhex("00112233445566778899aabbccddeeff")
KAT_CIPHER = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")

# FIPS-197 Appendix B example (different key/plaintext pair).
B_KEY = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
B_PLAIN = bytes.fromhex("3243f6a8885a308d313198a2e0370734")
B_CIPHER = bytes.fromhex("3925841d02dc09fbdc118597196a0b32")


def test_fips197_c1_encrypt():
    ks = aes128._expand_key(KAT_KEY)
    assert aes128.encrypt_block(ks, KAT_PLAIN) == KAT_CIPHER


def test_fips197_c1_decrypt():
    ks = aes128._expand_key(KAT_KEY)
    assert aes128.decrypt_block(ks, KAT_CIPHER) == KAT_PLAIN


def test_fips197_appendix_b():
    ks = aes128._expand_key(B_KEY)
    assert aes128.encrypt_block(ks, B_PLAIN) == B_CIPHER
    assert aes128.decrypt_block(ks, B_CIPHER) == B_PLAIN


def test_sbox_is_fips197_sbox():
    # Spot-check the generated S-box against published FIPS-197 entries.
    assert aes128.SBOX[0x00] == 0x63
    assert aes128.SBOX[0x01] == 0x7C
    assert aes128.SBOX[0x53] == 0xED
    assert aes128.SBOX[0xFF] == 0x16
    # Full inverse consistency: INV_SBOX must invert SBOX as a permutation.
    assert sorted(aes128.SBOX) == list(range(256))
    for i in range(256):
        assert aes128.INV_SBOX[aes128.SBOX[i]] == i


def test_key_schedule_length_and_tail():
    ks = aes128._expand_key(KAT_KEY)
    assert len(ks) == 176  # 11 round keys x 16 bytes
    # FIPS-197 Appendix A.1 last round key for the C.1 key.
    assert bytes(ks[160:176]) == bytes.fromhex("13111d7fe3944a17f307a78b4d2b30c5")


def test_ecb_round_trip_multiblock():
    rng = random.Random(8675309)
    key = bytes(rng.randrange(256) for _ in range(16))
    for nblocks in (1, 2, 7, 64):
        data = bytes(rng.randrange(256) for _ in range(16 * nblocks))
        enc = aes128.encrypt_ecb(key, data)
        assert len(enc) == len(data)
        assert enc != data
        assert aes128.decrypt_ecb(key, enc) == data


def test_ecb_blocks_are_independent():
    # ECB property: identical plaintext blocks encrypt identically — this is
    # exactly what the dvdbnd range decryption relies on (and why each
    # 16-byte block can be decrypted in isolation).
    key = KAT_KEY
    two = aes128.encrypt_ecb(key, KAT_PLAIN * 2)
    assert two[:16] == two[16:32] == aes128.encrypt_ecb(key, KAT_PLAIN)
