#!/usr/bin/env python3
"""Force the deployment target of an unsigned IPA to iOS 16.2.

Even when IPHONEOS_DEPLOYMENT_TARGET is 16.2, the Mach-O produced by a modern
Xcode still records the SDK it was built with (e.g. iOS 18/26) in
LC_BUILD_VERSION.sdk. dyld on older systems uses that value to decide whether
to enable newer runtime behaviours, so we pin both minos and sdk to 16.2.0 and
set Info.plist MinimumOSVersion to 16.2.

Usage: python3 scripts/patch-ios16.py <input.ipa> <output.ipa>
"""
import os
import plistlib
import struct
import sys
import zipfile

TARGET = (16 << 16) | (2 << 8) | 0  # 0x00100200 == 16.2.0
FAT_MAGICS = (0xCAFEBABE, 0xCAFEBABF)


def vtostr(v):
    return "%d.%d.%d" % ((v >> 16) & 0xFFFF, (v >> 8) & 0xFF, v & 0xFF)


def patch_slice(d, off):
    magic = struct.unpack_from("<I", d, off)[0]
    if magic == 0xFEEDFACF:       # MH_MAGIC_64
        hdr = 32
    elif magic == 0xFEEDFACE:     # MH_MAGIC
        hdr = 28
    else:
        raise RuntimeError("unexpected Mach-O magic 0x%08x" % magic)
    ncmds = struct.unpack_from("<I", d, off + 16)[0]
    pos = off + hdr
    changed = 0
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", d, pos)
        if cmd == 0x32:           # LC_BUILD_VERSION
            minos = struct.unpack_from("<I", d, pos + 12)[0]
            sdk = struct.unpack_from("<I", d, pos + 16)[0]
            struct.pack_into("<I", d, pos + 12, TARGET)
            struct.pack_into("<I", d, pos + 16, TARGET)
            changed += 1
            print("  LC_BUILD_VERSION: minos %s -> 16.2.0, sdk %s -> 16.2.0"
                  % (vtostr(minos), vtostr(sdk)))
        elif cmd == 0x25:         # LC_VERSION_MIN_IPHONEOS
            ver = struct.unpack_from("<I", d, pos + 8)[0]
            sdk = struct.unpack_from("<I", d, pos + 12)[0]
            struct.pack_into("<I", d, pos + 8, TARGET)
            struct.pack_into("<I", d, pos + 12, TARGET)
            changed += 1
            print("  LC_VERSION_MIN_IPHONEOS: %s -> 16.2.0 (sdk %s)"
                  % (vtostr(ver), vtostr(sdk)))
        if cmdsize == 0:
            raise RuntimeError("invalid load command size 0")
        pos += cmdsize
    return changed


def patch_macho(data):
    d = bytearray(data)
    magic_be = struct.unpack_from(">I", d, 0)[0]
    offsets = []
    if magic_be in FAT_MAGICS:
        nfat = struct.unpack_from(">I", d, 4)[0]
        is64 = magic_be == 0xCAFEBABF
        for i in range(nfat):
            o = 8 + i * (32 if is64 else 20)
            if is64:
                off = struct.unpack_from(">Q", d, o + 8)[0]
            else:
                off = struct.unpack_from(">I", d, o + 8)[0]
            offsets.append(off)
        print("FAT binary, %d slice(s)" % nfat)
    else:
        offsets.append(0)
        print("thin binary")
    total = 0
    for off in offsets:
        total += patch_slice(d, off)
    if total == 0:
        raise RuntimeError("no version load command found - refusing to output")
    return bytes(d)


def find_parts(z):
    plist_name = None
    for n in z.namelist():
        if n.startswith("Payload/") and n.count("/") == 2 and n.endswith("/Info.plist"):
            plist_name = n
            break
    if plist_name is None:
        raise RuntimeError("Payload/*.app/Info.plist not found")
    p = plistlib.loads(z.read(plist_name))
    exe = p.get("CFBundleExecutable", "TVADB")
    exe_name = plist_name.rsplit("/", 1)[0] + "/" + exe
    if exe_name not in z.namelist():
        raise RuntimeError("main binary not found: " + exe_name)
    return plist_name, exe_name, p


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 patch-ios16.py <input.ipa> <output.ipa>")
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    zin = zipfile.ZipFile(src)
    plist_name, exe_name, p = find_parts(zin)
    print("main binary:", exe_name)
    patched_bin = patch_macho(zin.read(exe_name))
    p["MinimumOSVersion"] = "16.2"
    raw_plist = zin.read(plist_name)
    fmt = plistlib.FMT_BINARY if raw_plist[:8] == b"bplist00" else plistlib.FMT_XML
    patched_plist = plistlib.dumps(p, fmt=fmt)

    out = os.path.abspath(dst)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == exe_name:
                data = patched_bin
            elif info.filename == plist_name:
                data = patched_plist
            ni = zipfile.ZipInfo(info.filename, info.date_time)
            ni.external_attr = info.external_attr
            ni.internal_attr = info.internal_attr
            ni.create_system = info.create_system
            ni.compress_type = info.compress_type
            ni.flag_bits = info.flag_bits & 0x800  # keep UTF-8 filename flag only
            zout.writestr(ni, data)
    zin.close()

    # --- self check ---
    z = zipfile.ZipFile(out)
    assert z.testzip() is None, "output zip is corrupt"
    q = plistlib.loads(z.read(plist_name))
    assert q["MinimumOSVersion"] == "16.2"
    d = z.read(exe_name)
    magic_be = struct.unpack_from(">I", d, 0)[0]
    offs = [0]
    if magic_be in FAT_MAGICS:
        nfat = struct.unpack_from(">I", d, 4)[0]
        is64 = magic_be == 0xCAFEBABF
        offs = []
        for i in range(nfat):
            o = 8 + i * (32 if is64 else 20)
            offs.append(struct.unpack_from(">Q" if is64 else ">I", d, o + (8 if is64 else 8))[0])
    for off in offs:
        ncmds = struct.unpack_from("<I", d, off + 16)[0]
        pos = off + (32 if struct.unpack_from("<I", d, off)[0] == 0xFEEDFACF else 28)
        for _ in range(ncmds):
            cmd, sz = struct.unpack_from("<II", d, pos)
            if cmd == 0x32:
                mn, sk = struct.unpack_from("<II", d, pos + 12)
                assert mn == TARGET and sk == TARGET, "version patch failed"
                print("verified: minos=%s sdk=%s" % (vtostr(mn), vtostr(sk)))
            pos += sz
    for i in z.infolist():
        if i.filename == exe_name:
            print("verified: executable mode", oct(i.external_attr >> 16))
    print("OK ->", out)


if __name__ == "__main__":
    main()
