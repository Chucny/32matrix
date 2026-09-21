"""Alignment-aware ZIP reader/writer used to repack APKs in place.

Android needs uncompressed entries aligned inside the APK: ``.so`` files must
sit on a page boundary (16 KiB on Android 15+ devices, 4 KiB before) and other
uncompressed entries on a 4 byte boundary.  ``zipfile`` cannot express this, so
the writer below pads each local file header with a Zipalign-style extra field
to place the payload at the requested alignment.
"""
from __future__ import annotations

import os
import struct
import zlib
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

ZIP_LOCAL = 0x04034B50
ZIP_CENTRAL = 0x02014B50
ZIP_EOCD = 0x06054B50

STORED = 0
DEFLATED = 8

DEFAULT_ALIGN = 4
SO_PAGE = 16384
_PAD_ID = 0xD935  # id used by Android's zipalign for its padding extra field

_CHUNK = 1 << 20


def _deflate(raw: bytes) -> bytes:
    """Raw DEFLATE (no zlib header/trailer) as required by the ZIP format."""
    comp = zlib.compressobj(6, zlib.DEFLATED, -15)
    return comp.compress(raw) + comp.flush()


def _dos_time(dt: Tuple[int, int, int, int, int, int]) -> Tuple[int, int]:
    y, m, d, H, M, S = dt
    if y < 1980:
        y = 1980
    dos_date = ((y - 1980) << 9) | (m << 5) | d
    dos_time = (H << 11) | (M << 5) | (S // 2)
    return dos_time, dos_date


@dataclass
class Entry:
    """A single zip member.

    Exactly one of ``data`` (materialised bytes) or ``src`` (raw slice of a file
    on disk, ``(path, offset, length, crc)``) is set.  ``src`` avoids loading
    multi-hundred-megabyte assets into memory.
    """

    name: str
    method: int = STORED
    date_time: Tuple[int, int, int, int, int, int] = (2009, 1, 1, 0, 0, 0)
    external_attr: int = 0
    comment: bytes = b""
    align: int = DEFAULT_ALIGN
    data: Optional[bytes] = None
    src: Optional[Tuple[str, int, int, int]] = None

    def sizes(self) -> Tuple[int, int, int]:
        if self.src is not None:
            _, _, length, crc = self.src
            return crc, length, length
        raw = self.data if self.data is not None else b""
        crc = zlib.crc32(raw) & 0xFFFFFFFF
        if self.method == DEFLATED and raw:
            csize = len(_deflate(raw))
        else:
            csize = len(raw)
        return crc, csize, len(raw)

    def payload_bytes(self) -> bytes:
        raw = self.data if self.data is not None else b""
        if self.method == DEFLATED and raw:
            return _deflate(raw)
        return raw


def align_for(name: str, method: int, page: int = SO_PAGE) -> int:
    if method != STORED:
        return 1
    if name.endswith(".so"):
        return page
    return DEFAULT_ALIGN


def _raw_data_offset(path: str, info: zipfile.ZipInfo) -> Tuple[int, int]:
    with open(path, "rb") as f:
        f.seek(info.header_offset)
        hdr = f.read(30)
    (sig, ver, flags, method, t, d, crc, csize, usize, nlen, elen) = struct.unpack(
        "<IHHHHHIIIHH", hdr
    )
    if sig != ZIP_LOCAL:
        raise zipfile.BadZipFile("bad local header for %s" % info.filename)
    size = usize if usize not in (0xFFFFFFFF,) else info.file_size
    return info.header_offset + 30 + nlen + elen, size


def read_entries(path: str, page: int = SO_PAGE, align_data: bool = True) -> List[Entry]:
    """Read every member of *path* as a list of :class:`Entry`."""
    entries: List[Entry] = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            name = info.filename
            if info.compress_type == zipfile.ZIP_STORED:
                off, size = _raw_data_offset(path, info)
                entries.append(
                    Entry(
                        name=name,
                        method=STORED,
                        date_time=info.date_time,
                        external_attr=info.external_attr,
                        comment=info.comment,
                        align=align_for(name, STORED, page) if align_data else DEFAULT_ALIGN,
                        src=(path, off, size, info.CRC & 0xFFFFFFFF),
                    )
                )
            else:
                entries.append(
                    Entry(
                        name=name,
                        method=DEFLATED,
                        date_time=info.date_time,
                        external_attr=info.external_attr,
                        comment=info.comment,
                        align=1,
                        data=z.read(name),
                    )
                )
    return entries


def make_entry(name: str, path: str, *, method: int = STORED, page: int = SO_PAGE,
               align: Optional[int] = None) -> Entry:
    """Build an entry that stores *path* verbatim (used for the bundled guest)."""
    size = os.path.getsize(path)
    crc = _crc32_file(path)
    if align is None:
        align = align_for(name, method, page)
    if method == STORED:
        return Entry(name=name, method=STORED, align=align, src=(path, 0, size, crc))
    with open(path, "rb") as f:
        return Entry(name=name, method=DEFLATED, align=1, data=f.read())


def _crc32_file(path: str) -> int:
    crc = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc)
    return crc & 0xFFFFFFFF


def write_zip(dst: str, entries: List[Entry], comment: bytes = b"") -> None:
    central = []
    with open(dst, "wb") as fp:
        for e in entries:
            offset = fp.tell()
            name = e.name.encode("utf-8")
            flags = 0x0800 if any(b > 127 for b in name) else 0
            method = e.method
            align = e.align if method == STORED else 1
            if align > 1:
                pad = (-(offset + 30 + len(name) + 4)) % align
                extra = struct.pack("<HH", _PAD_ID, pad) + b"\x00" * pad
            else:
                extra = b""
            crc, csize, usize = e.sizes()
            dostime, dosdate = _dos_time(e.date_time)
            fp.write(
                struct.pack(
                    "<IHHHHHIIIHH",
                    ZIP_LOCAL, 20, flags, method, dostime, dosdate,
                    crc, csize, usize, len(name), len(extra),
                )
            )
            fp.write(name)
            fp.write(extra)
            if e.src is not None:
                path, off, length, _ = e.src
                with open(path, "rb") as rf:
                    rf.seek(off)
                    remaining = length
                    while remaining > 0:
                        chunk = rf.read(min(_CHUNK, remaining))
                        if not chunk:
                            raise IOError("unexpected EOF copying %s" % e.name)
                        fp.write(chunk)
                        remaining -= len(chunk)
            else:
                fp.write(e.payload_bytes())
            central.append((e, offset, flags, dostime, dosdate, len(name), crc, csize, usize))

        cd_offset = fp.tell()
        for e, offset, flags, dostime, dosdate, nlen, crc, csize, usize in central:
            name = e.name.encode("utf-8")
            fp.write(
                struct.pack(
                    "<IHHHHHHIIIHHHHHII",
                    ZIP_CENTRAL, 0x031E, 20, flags, e.method, dostime, dosdate,
                    crc, csize, usize, nlen, 0, len(e.comment), 0, 0,
                    e.external_attr, offset,
                )
            )
            fp.write(name)
            fp.write(e.comment)
        cd_size = fp.tell() - cd_offset
        fp.write(
            struct.pack(
                "<IHHHHIIH",
                ZIP_EOCD, 0, 0, len(central), len(central), cd_size, cd_offset,
                len(comment),
            )
        )
        if comment:
            fp.write(comment)


def is_signature_entry(name: str) -> bool:
    upper = name.upper()
    if not upper.startswith("META-INF/"):
        return False
    return upper.endswith((".RSA", ".DSA", ".EC", ".SF")) or upper.endswith(
        "META-INF/MANIFEST.MF"
    )


def replace_entry(entries: List[Entry], name: str, new: Entry) -> bool:
    for i, e in enumerate(entries):
        if e.name == name:
            entries[i] = new
            return True
    return False


def drop_entries(entries: List[Entry], names) -> List[Entry]:
    names = set(names)
    return [e for e in entries if e.name not in names]


def strip_abi(entries: List[Entry], abi: str) -> List[Entry]:
    prefix = "lib/%s/" % abi
    return [e for e in entries if not e.name.startswith(prefix)]
