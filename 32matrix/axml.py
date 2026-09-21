"""Minimal binary AndroidManifest.xml (AXML) reader.

Only what 32matrix needs is implemented: the string pool, the resource map and
start/end elements with attributes.  Enough to recover the package name,
version, SDK levels, ABI-ish flags, application node and launcher activity.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

RES_STRING_POOL = 0x0001
RES_XML = 0x0003
RES_XML_START_NS = 0x0100
RES_XML_END_NS = 0x0101
RES_XML_START_ELEMENT = 0x0102
RES_XML_END_ELEMENT = 0x0103
RES_XML_CDATA = 0x0104
RES_XML_RESOURCE_MAP = 0x0180

UTF8_FLAG = 1 << 8

TYPE_NULL = 0x00
TYPE_REFERENCE = 0x01
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11
TYPE_BOOLEAN = 0x12

ANDROID_NS = "http://schemas.android.com/apk/res/android"

# android attribute resource ids we care about
RID_NAME = 0x01010003
RID_LABEL = 0x01010001
RID_ICON = 0x01010002
RID_VERSION_CODE = 0x0101021B
RID_VERSION_NAME = 0x0101021C
RID_MIN_SDK = 0x0101020C
RID_TARGET_SDK = 0x01010270
RID_EXTRACT_NATIVE_LIBS = 0x010104EA
RID_IS_FEATURE_SPLIT = 0x0101055B
RID_DEBUGGABLE = 0x0101000F

ACTION_MAIN = "android.intent.action.MAIN"
CATEGORY_LAUNCHER = "android.intent.category.LAUNCHER"


class AXMLDecodeError(Exception):
    pass


@dataclass
class Attr:
    ns: str
    name: str
    rid: int
    data_type: int
    data: int
    value: object

    @property
    def key(self) -> str:
        if self.ns == ANDROID_NS:
            return "android:" + self.name
        return self.name


@dataclass
class Element:
    name: str
    attrs: List[Attr] = field(default_factory=list)
    children: List["Element"] = field(default_factory=list)

    def get(self, key: str, default=None):
        for a in self.attrs:
            if a.key == key:
                return a.value
        return default

    def get_rid(self, rid: int, default=None):
        for a in self.attrs:
            if a.rid == rid:
                return a.value
        return default

    def find_all(self, name: str):
        return [c for c in self.children if c.name == name]


def _parse_string_pool(data: bytes, base: int) -> List[str]:
    header_size = struct.unpack_from("<H", data, base + 2)[0]
    string_count, style_count, flags, strings_start, styles_start = struct.unpack_from(
        "<IIIII", data, base + 8
    )
    is_utf8 = bool(flags & UTF8_FLAG)
    offsets_base = base + header_size
    strings = []
    for i in range(string_count):
        off = struct.unpack_from("<I", data, offsets_base + 4 * i)[0]
        pos = base + strings_start + off
        if is_utf8:
            # char count
            b0 = data[pos]
            if b0 & 0x80:
                pos += 2
            else:
                pos += 1
            # byte count
            b0 = data[pos]
            if b0 & 0x80:
                blen = ((b0 & 0x7F) << 8) | data[pos + 1]
                pos += 2
            else:
                blen = b0
                pos += 1
            s = data[pos : pos + blen].decode("utf-8", "replace")
        else:
            clen = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            s = data[pos : pos + clen * 2].decode("utf-16-le", "replace")
        strings.append(s)
    return strings


def parse_manifest(data: bytes) -> Element:
    """Parse an AXML document and return the root element with children."""
    if len(data) < 8:
        raise AXMLDecodeError("file too small to be AXML")
    magic, = struct.unpack_from("<H", data, 0)
    if magic != RES_XML:
        raise AXMLDecodeError("not a binary XML resource (is this AXML/compiled?)")

    strings: List[str] = []
    resource_ids: List[int] = []
    root: Optional[Element] = None
    stack: List[Element] = []

    offset = 8  # skip RES_XML header (type/headerSize/size)
    while offset + 8 <= len(data):
        ctype, header_size, csize = struct.unpack_from("<HHI", data, offset)
        if csize == 0:
            break
        if ctype == RES_STRING_POOL:
            strings = _parse_string_pool(data, offset)
        elif ctype == RES_XML_RESOURCE_MAP:
            count = (csize - header_size) // 4
            resource_ids = list(struct.unpack_from("<%dI" % count, data, offset + header_size))
        elif ctype == RES_XML_START_ELEMENT:
            name_idx = struct.unpack_from("<I", data, offset + 20)[0]
            attr_start, attr_size, attr_count = struct.unpack_from("<HHH", data, offset + 24)
            attrs: List[Attr] = []
            # attribute_start is relative to the ResXMLTree_attrExt struct, which
            # begins after the 8 byte chunk header + line/comment (16 bytes).
            apos = offset + 16 + attr_start
            for _ in range(attr_count):
                ns_i, name_i, raw_i = struct.unpack_from("<III", data, apos)
                dsize, res0, dtype, ddata = struct.unpack_from("<HBBI", data, apos + 12)
                ns = strings[ns_i] if ns_i != 0xFFFFFFFF and ns_i < len(strings) else ""
                aname = strings[name_i] if name_i != 0xFFFFFFFF and name_i < len(strings) else ""
                rid = (
                    resource_ids[name_i]
                    if name_i != 0xFFFFFFFF and name_i < len(resource_ids)
                    else 0
                )
                if dtype == TYPE_STRING:
                    val = strings[ddata] if ddata < len(strings) else ""
                elif dtype in (TYPE_INT_DEC, TYPE_INT_HEX):
                    val = ddata
                elif dtype == TYPE_BOOLEAN:
                    val = bool(ddata)
                elif dtype == TYPE_REFERENCE:
                    val = "@0x%x" % ddata
                else:
                    val = ddata
                attrs.append(Attr(ns=ns, name=aname, rid=rid, data_type=dtype, data=ddata, value=val))
                apos += attr_size
            el = Element(name=strings[name_idx] if name_idx < len(strings) else "", attrs=attrs)
            if stack:
                stack[-1].children.append(el)
            else:
                root = el
            stack.append(el)
        elif ctype == RES_XML_END_ELEMENT:
            if stack:
                stack.pop()
        offset += csize

    if root is None:
        raise AXMLDecodeError("no root element found")
    return root
