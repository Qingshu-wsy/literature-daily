"""Windows user-scoped encryption for locally stored portal passwords."""
from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _transform(data: bytes, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("门户密码的加密存储仅支持 Windows")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_pointer = ctypes.POINTER(_DataBlob)
    if decrypt:
        crypt32.CryptUnprotectData.argtypes = [
            blob_pointer,
            ctypes.POINTER(wintypes.LPWSTR),
            blob_pointer,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            blob_pointer,
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
    else:
        crypt32.CryptProtectData.argtypes = [
            blob_pointer,
            wintypes.LPCWSTR,
            blob_pointer,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            blob_pointer,
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    output = _DataBlob()

    if decrypt:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            0x1,
            ctypes.byref(output),
        )
    else:
        ok = crypt32.CryptProtectData(
            ctypes.byref(source),
            "LitDaily portal password",
            None,
            None,
            None,
            0x1,
            ctypes.byref(output),
        )

    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def encrypt_password(password: str) -> str:
    encrypted = _transform(password.encode("utf-8"), decrypt=False)
    return base64.b64encode(encrypted).decode("ascii")


def decrypt_password(value: str) -> str:
    try:
        encrypted = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ValueError("门户密码的加密数据格式无效") from exc
    return _transform(encrypted, decrypt=True).decode("utf-8")
