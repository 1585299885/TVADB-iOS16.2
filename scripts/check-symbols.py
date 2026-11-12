#!/usr/bin/env python3
"""Verify the built IPA has no strongly-bound iOS 17 SwiftUI symbols.

A binary that still references ContentUnavailableView / SensoryFeedback /
contentMargins as a *strong* import will be killed by dyld on iOS 16.2 with
"Symbol not found". This script parses LC_DYLD_CHAINED_FIXUPS and fails if any
such import is still bound to a concrete dylib.

Usage: python3 scripts/check-symbols.py <file.ipa>
"""
import plistlib
import struct
import sys
import zipfile

IOS17 = [
    "ContentUnavailableView", "SensoryFeedback", "sensoryFeedback",
    "contentMargins", "ContentMarginPlacement", "safeAreaPadding",
    "ScrollTarget", "scrollTarget", "scrollPosition", "containerRelativeFrame",
    "symbolEffect", "PhaseAnimator", "KeyframeAnimator", "visualEffect",
    "VisualEffect", "scrollTransition", "geometryGroup", "invalidatableContent",
    "typesettingLanguage", "paletteSelectionEffect", "buttonRepeatBehavior",
    "springLoading", "defaultScrollAnchor", "scrollBounceBehavior",
    "scrollClipDisabled", "listRowSpacing", "listSectionSpacing",
    "toolbarTitleDisplayMode", "MeshGradient", "TextRenderer", "onGeometryChange",
    "presentationBackground", "presentationCornerRadius", "inspector",
]


def load_commands(d, off):
    magic = struct.unpack_from("<I", d, off)[0]
    hdr = 32 if magic == 0xFEEDFACF else 28
    ncmds = struct.unpack_from("<I", d, off + 16)[0]
    pos = off + hdr
    for _ in range(ncmds):
        cmd, sz = struct.unpack_from("<II", d, pos)
        yield cmd, sz, pos
        pos += sz


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 check-symbols.py <file.ipa>")
        sys.exit(1)
    z = zipfile.ZipFile(sys.argv[1])
    plist_name = next(n for n in z.namelist()
                      if n.startswith("Payload/") and n.count("/") == 2
                      and n.endswith("/Info.plist"))
    p = plistlib.loads(z.read(plist_name))
    exe = plist_name.rsplit("/", 1)[0] + "/" + p.get("CFBundleExecutable", "TVADB")
    d = z.read(exe)
    print("checking", exe, "(%d bytes)" % len(d))

    cf = None
    dylibs = []
    for cmd, sz, pos in load_commands(d, 0):
        if cmd == 0x80000034:  # LC_DYLD_CHAINED_FIXUPS
            cf = struct.unpack_from("<II", d, pos + 8)
        if cmd in (0xC, 0x80000018, 0x8000001F, 0x80000023):
            no = struct.unpack_from("<I", d, pos + 8)[0]
            dylibs.append(d[pos + no:d.find(b"\0", pos + no)].decode("utf8", "replace"))
    if not cf:
        print("no chained fixups - nothing to check")
        return

    b = cf[0]
    _, _, imp_off, sym_off, imp_cnt, _, _ = struct.unpack_from("<7I", d, b)
    ib, sb = b + imp_off, b + sym_off

    def dec(v):
        lo = v & 0xFF
        return v >> 9, (v >> 8) & 1, (lo - 256 if lo >= 0x80 else lo)

    def libname(o):
        if 1 <= o <= len(dylibs):
            return dylibs[o - 1].split("/")[-1]
        return {0: "self", -1: "main", -2: "flat", -3: "WEAK_LOOKUP"}.get(o, "ord%d" % o)

    hits = []
    for i in range(imp_cnt):
        v = struct.unpack_from("<I", d, ib + i * 4)[0]
        no, weak, lo = dec(v)
        e = d.find(b"\0", sb + no)
        name = d[sb + no:e].decode("utf8", "replace")
        if weak == 0 and lo > 0 and any(k in name for k in IOS17):
            hits.append((libname(lo), name))

    print("strongly-bound iOS 17 symbols:", len(hits))
    for lib, name in hits[:20]:
        print("  [%s] %s" % (lib, name[:120]))
    if hits:
        print("\nFAIL: this IPA will crash on iOS 16.2 (Symbol not found).")
        print("Remove the remaining iOS 17 API usage from the Swift sources and rebuild.")
        sys.exit(1)
    print("PASS: no iOS 17 SwiftUI symbols are strongly bound.")


if __name__ == "__main__":
    main()
