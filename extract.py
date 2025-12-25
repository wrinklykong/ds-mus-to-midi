#!/usr/bin/python3

import struct
import string
import json

ALLOWED_FILENAME_LETTERS = string.ascii_letters + string.digits + '.'
TEST_FILE = "data/music/decoder.mus"
HEADER_BYTES = 0x568
SEQ_INFO_BYTES = 0x20C  # 0x774-0x568
SAMPLE_STRUCT_SIZE = 0x2c
SAMPLE_STRUCT_FORMAT = "<20sIIIIII"
SAMPLE_STRUCT = struct.Struct(SAMPLE_STRUCT_FORMAT)


def remove_trailing_zeros_from_str(s):
    return s.replace('\x00', '')


def is_valid_sample_name(peaked):
    return all([chr(b) in ALLOWED_FILENAME_LETTERS for b in peaked])


class Sample:
    def __init__(self, sname, stype, ssize, siden, sloops, sloope, edata, nsec):
        self.sname = sname
        self.stype = stype
        self.ssize = ssize
        self.siden = siden
        self.sloops = sloops
        self.sloope = sloope
        self.edata = edata
        self.nsec = nsec
    
    def __str__(self):
        s = [f"Sample Name: {self.sname}",
             f"Type: {self.stype}",
             f"Size: {self.ssize} bytes",
             f"Iden: {self.siden}",
             f"Loop start: {self.sloops}",
             f"Loop end: {self.sloope}",
             f'Num sections: {self.nsec}']
        return "\n\t".join(s)


class VirtualFile:
    data = None
    pos = 0

    def __init__(self, data):
        self.data = data
        self.size = len(data)

    def read(self, num):
        self.pos += num
        return self.data[self.pos-num:self.pos]
    
    def peak(self, num):
        return self.data[self.pos:self.pos+num]


def get_sample_data(vfile):
    samples = []
    VF_sample_info = VirtualFile(vfile.read(HEADER_BYTES))
    # Skip title if exists
    while VF_sample_info.peak(1) != b'\x00':
        VF_sample_info.read(1)
    # Skip empty header if any
    while VF_sample_info.peak(1) == b'\x00':
        VF_sample_info.read(1)
    # Read sample information
    next_session = False
    num_samples = 0
    while True:
        num_sections = 0
        # get a section of data
        sample_struct = VF_sample_info.read(SAMPLE_STRUCT_SIZE)
        sample_name, sample_type, sample_size, sample_iden, sample_loop_start, sample_loop_end, extra_data = SAMPLE_STRUCT.unpack(sample_struct)
        # if the value at 1c is == 0, then we've reached the end of the info
        if sample_iden == 0:
            break
        # First 24 bytes are the the sample name, which is loaded in from /music/%s
        sample_name = remove_trailing_zeros_from_str(sample_name.decode('utf8'))
        # peak until the stringname contains .pcm
        while True:
            sample_struct = VF_sample_info.peak(SAMPLE_STRUCT_SIZE)
            sname, _, __, siden, ___, _____, ______ = SAMPLE_STRUCT.unpack(sample_struct)
            # We've hit the end of the section
            if siden == 0:
                break
            if sname == b'\x00'*20:
                # Extra data from current sample, keep reading...
                VF_sample_info.read(SAMPLE_STRUCT_SIZE)
                num_sections += 1
            else:
                break
        s = Sample(sample_name, sample_type, sample_size, sample_iden, sample_loop_start, sample_loop_end, extra_data, num_sections)
        samples.append(s)
        print(s)
    return samples


def get_seq_data(vfile):
    # read next bytes
    sequences = []
    found_zero = False
    VF_seq = VirtualFile(vfile.read(SEQ_INFO_BYTES))
    while True:
        next_byte = struct.unpack("<I", VF_seq.read(4))[0]
        if next_byte == 0:
            if found_zero:
                break
            else:
                found_zero = True
                sequences.append(0)
        else:
            sequences.append(next_byte)
    return sequences
    

def main():
    with open(TEST_FILE, "rb") as f:
        read_data = f.read()

    VF = VirtualFile(read_data)
    # Parse the sample header from 0x0 - 0x568
    samples = get_sample_data(VF)
    num_samples = len(samples)
    print(f'[+]  Num samples: {num_samples}')
    # parse the seq header from 0x568 - 0x774
    order = get_seq_data(VF)
    num_seq = len(order)
    print(f'Num seq: {num_seq}; order: {order}')
    # Now we get into the track information... 0x774 til end
    # calculate the end
    len_tracks = VF.size - 0x774
    print(len_tracks)
    size_of_section = len_tracks / num_samples
    # there are EVENLY divided sections
    print(size_of_section)
    return
    BUFFER_BYTES = (0xFF, 0x0)
    all_data = []
    cur_data = b''
    num_buff = 0
    thing = {}
    while True:
        # read 4 at at ime
        peaked = VF.peak(4)
        if peaked == b'':
            break
        if all([p in BUFFER_BYTES for p in peaked]):
            # we hit buffer, read on
            if len(cur_data) >= 2*num_samples:
                print(f"[+]  Found seq header at: {hex(VF.pos)}")
                seq_num = cur_data[0]
                info_blob = ' '.join([hex(p) for p in cur_data[1:]])
                if seq_num in thing:
                    thing[seq_num].append(info_blob)
                else:
                    thing.update({cur_data[0]: [info_blob]})
            cur_data = b''
            VF.read(4)
            num_buff += 4
        else:
            # we hit some data, report it
            num_buff = 0
            cur_data += VF.read(4)
    # print(json.dumps(thing, indent=4))
main()
