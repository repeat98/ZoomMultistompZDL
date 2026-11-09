"""Verify a cover relink changes only relocated constant operands in DSP code."""
import struct
from gen_init_materialize import _read_elf_sections

def verify_audio(old, new, size):
    blocks=[]
    for z in (old,new):
        s=_read_elf_sections(z.elf);t=s['.text'];r=s['.rela.dyn'];sy=s['.dynsym'];c=s['.const']
        audio=bytearray(z.elf[t['offset']:t['offset']+size])
        for at in range(r['offset'],r['offset']+r['size'],12):
            off,info,add=struct.unpack_from('<IIi',z.elf,at)
            relative=off-t['addr']
            if 0<=relative<size:
                typ=info&255
                target=struct.unpack_from('<I',z.elf,sy['offset']+(info>>8)*16+4)[0]+add
                assert typ in (9,10) and c['addr']<=target<c['addr']+c['size']
                word=struct.unpack_from('<I',audio,relative)[0]
                assert ((word>>7)&65535)==((target if typ==9 else target>>16)&65535)
                struct.pack_into('<I',audio,relative,word&~(65535<<7))
        blocks.append(audio)
    assert blocks[0]==blocks[1], 'Cover relink changed DSP instructions'
