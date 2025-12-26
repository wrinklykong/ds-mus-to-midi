#!/usr/bin/python3

import struct
import string
import json
import glob
from pathlib import Path

ALLOWED_FILENAME_LETTERS = string.ascii_letters + string.digits + '.'
TEST_FILE = "data/music/credits.mus"
TITLE_HEADER = 20  # bytes reserved for the header, if it exists
HEADER_BYTES = 0x568
# HEADER CONTENTS:
## 2c x 31 channels (2x16?)
SEQ_INFO_BYTES = 0x20C  # 0x774-0x568
SAMPLE_STRUCT_SIZE = 0x2c
SAMPLE_STRUCT_FORMAT = "<20sIIIIII"
SAMPLE_STRUCT = struct.Struct(SAMPLE_STRUCT_FORMAT)


def remove_trailing_zeros_from_str(s):
    return s.replace('\x00', '')


class Sample:
    def __init__(self, sname, stype, ssize, siden, sloops, sloope, edata, snume):
        self.sname = sname
        self.stype = stype
        self.ssize = ssize
        self.siden = siden
        self.sloops = sloops
        self.sloope = sloope
        self.edata = edata
        self.snume = snume
    
    def __str__(self):
        s = [f"Sample Name: {self.sname}",
             f"Type: {self.stype}",
             f"Size: {self.ssize} bytes",
             f"Iden: {self.siden}",
             f"Loop start: {self.sloops}",
             f"Loop end: {self.sloope}",
             f'Section num: {self.snume}']
        return "\n\t".join(s)


class VirtualFile:
    data = None
    pos = 0
    size = -1

    def __init__(self, data):
        self.data = data
        self.size = len(data)

    def read(self, num):
        self.pos += num
        return self.data[self.pos-num:self.pos]
    
    def peak(self, num):
        return self.data[self.pos:self.pos+num]


def get_sample_data(vfile):
    # Technically, there is a 31 max sample length here
    samples = [None] * 31
    VF_sample_info = VirtualFile(vfile.read(HEADER_BYTES))
    # Skip title if exists
    while VF_sample_info.peak(1) != b'\x00':
        VF_sample_info.read(1)
    # Skip empty header if any
    while VF_sample_info.peak(1) == b'\x00':
        VF_sample_info.read(1)
    # Read sample information
    next_session = False
    cur_section = 0
    while True:
        # get a section of data
        sample_struct = VF_sample_info.read(SAMPLE_STRUCT_SIZE)
        if sample_struct == b'':
            break
        cur_section += 1
        sample_name, sample_type, sample_size, sample_iden, sample_loop_start, sample_loop_end, extra_data = SAMPLE_STRUCT.unpack(sample_struct)
        # if the value at 1c is == 0, then we've reached the end of the info
        if sample_iden == 0:
            break
        if sample_name == b'\x00'*20:
            # Extra data from current sample, keep reading...
            VF_sample_info.read(SAMPLE_STRUCT_SIZE)
            cur_section += 1
            continue
        # First 24 bytes are the the sample name, which is loaded in from /music/%s
        sample_name = remove_trailing_zeros_from_str(sample_name.decode('utf8'))
        s = Sample(sample_name, sample_type, sample_size, sample_iden, sample_loop_start, sample_loop_end, extra_data, cur_section)
        samples[cur_section-1] = s
        # print(s)
    # print(samples)
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
    num_channels = sequences[0]
    sequences = sequences[1:]
    return num_channels, sequences


def display_seq_info(seq_info):
    header = "0000|1111|2222|3333|4444|5555|6666|7777|8888|9999|AAAA|BBBB|CCCC|DDDD|EEEE|FFFF"
    contents = []
    for x in seq_info:
        # split into 4s to add the barrier between
        split_thing = []
        for i in range(len(x)//4):
            split_thing.append(''.join([str(y) for y in x[i*4:(i+1)*4]]))
        contents.append('|'.join(split_thing))
    print(header)
    for c in contents:
        print(c)
    print('')


def get_note_info(vfile, num_channels):

    data_size = vfile.size - SEQ_INFO_BYTES - HEADER_BYTES
    notes_file = VirtualFile(vfile.read(data_size))

    # 6 = length of the struct
    # 64 = guessed length of the thingy
    section_size = 6 * num_channels * 64
    num_seqs = int(data_size / section_size)
    notes_per_seq = section_size // 6

    for i in range(num_seqs):
        seq_info = [None] * num_channels
        # split into 6 byte parts for each thing
        for _ in range(64):
            for channel in range(num_channels):
                note = notes_file.read(6)
                if seq_info[channel] == None:
                    seq_info[channel] = [note[0]]
                else:
                    seq_info[channel].append(note[0])
        display_seq_info(seq_info)


def process_mus_file(filename):
    with open(filename, "rb") as f:
        read_data = f.read()
    VF = VirtualFile(read_data)
    # Parse the sample header from 0x0 - 0x568
    samples = get_sample_data(VF)
    for s in samples:
        if s:
            print(s)
    num_samples = len([s for s in samples if s is not None])
    # parse the seq header from 0x568 - 0x774
    num_channels, order = get_seq_data(VF)
    # Now we get into the track information... 0x774 til end
    get_note_info(VF, num_channels)
    # calculate the end
    len_tracks = VF.size - 0x774
    section_size = 6 * num_channels * 64
    return len_tracks, num_samples, order

def main():
    # read all files that end with .mus, get the size of the data and get some info on it...
    # with open(TEST_FILE, "rb") as f:
    #     read_data = f.read()
    # 
    # VF = VirtualFile(read_data)
    # # Parse the sample header from 0x0 - 0x568
    # samples = get_sample_data(VF)
    # num_samples = len(samples)
    # # parse the seq header from 0x568 - 0x774
    # order = get_seq_data(VF)
    # num_seq = len(order)
    # num_sections = max(order) + 1
    # print(f'Num seq: {num_seq}; order: {order}, num_sections: {num_sections}')
    # # Now we get into the track information... 0x774 til end
    # # calculate the end
    # len_tracks = VF.size - 0x774
    # print(len_tracks)
    # # 6 is assumed note info struct length
    # num_notes = len_tracks / 6
    # print(f'{num_notes=}')
    # # there are EVENLY divided sections
    # size_of_section = num_notes / num_sections
    # print(f'{size_of_section=}')
    # do some research on all of the bytes n stuff
    # ret = get_note_info(VF)
    # a = set()
    # for r in ret:
    #     if r[0] == 1:
    #         a.add(hex(r[2] & ~0x0F))
    # print(a)
    # print([hex(a) for a in ret if a[0] == 5])
    # print(json.dumps(thing, indent=4))
    data = {}
    for mfile in glob.glob("data/music/pokerintro.mus"):
        filename = Path(mfile).name
        tracklen, nsample, seqs = process_mus_file(mfile)
        num_channels = seqs[0]
        # probably some stereo thing
        section_size = 6 * num_channels * 64
        # No idea wtf this shit is
        #  "NumSequencesPlayed": seqs[1],
        data.update({filename: {
            "TrackLen": tracklen,
            "NumSamples": nsample,
            "NumChannels": seqs[0],
            "NumSequencesPlayed": seqs[1],
            # "Seqs": seqs[2:],
            "CalcNumSeqs": tracklen/section_size
        }})
    print(json.dumps(data, indent=4))

main()
