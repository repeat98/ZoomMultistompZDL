"""Replace the pinned ZDL source's firmware-word comparisons with checksums."""
import hashlib
from pathlib import Path
import re
import sys

path = Path(sys.argv[1]) / "src/custom/common/zvis.h"
text = path.read_text()
if hashlib.sha256(path.read_bytes()).hexdigest() != "be11b802f6b16a3d03038ed1a82a8adb0fc8ab8f017c6e72ff3989133f965812":
    sys.exit("Unexpected display guard source revision")
start = text.index("static const ZvFw zv_fws")
end = text.index("enum { ZV_IDLE", start)
table = text[start:end]
pair = r"\{\s*(0x[0-9A-Fa-f]+|0)u,\s*(0x[0-9A-Fa-f]+|0)u\s*\}"
blocks = re.compile(r"\{\s*((?:" + pair + r"(?:,\s*)?)+)\s*\}", re.S)
def checksummed(match):
    entries = [(int(a, 0), int(v, 0)) for a, v in re.findall(pair, match[1])]
    digest = 2166136261
    addresses = []
    for address, word in entries:
        if address:
            for number in [address, word]:
                digest = ((digest ^ number) * 16777619) & 0xffffffff
            addresses.append(f"0x{address:08X}u")
    return "{ " + ", ".join(addresses) + " }, " + f"0x{digest:08X}u"
table, count = blocks.subn(checksummed, table)
assert count == 2
text = text[:start] + table + text[end:]
text = text.replace("uint32_t sig[10][2];", "uint32_t sig[10], sig_hash;")
start = text.index("/* Do all fingerprint words")
end = text.index("/* Which known OS", start)
text = text[:start] + """/* Check the selected instruction locations against a single OS checksum. */
ZV_INLINE(zv_sig_ok)
static inline int zv_sig_ok(const ZvFw *fw)
{
    uint32_t checksum = 2166136261u;
    unsigned i;
    for (i = 0; i < 10u && fw->sig[i]; ++i) {
        uint32_t address = fw->sig[i];
        if (!zv_in_ram(address) || (address & 3u)) return 0;
        checksum = (checksum ^ address) * 16777619u;
        checksum = (checksum ^ ZV_U32(address)) * 16777619u;
    }
    return i > 0u && checksum == fw->sig_hash;
}

""" + text[end:]
text = text.replace("zv_sig_ok(&zv_fws[k].sig[0][0])", "zv_sig_ok(&zv_fws[k])")
text = text.replace("zv_sig_ok(&t->sig[0][0])", "zv_sig_ok(t)")
text = text.replace("z->fw.sig[0][0]", "z->fw.sig[0]")
path.write_text(text)
