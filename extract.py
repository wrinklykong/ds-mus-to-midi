#!/usr/bin/python3

import struct
import string
import json
import glob
from pathlib import Path

from midiutil.MidiFile import MIDIFile

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

NOTE_SCALE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def remove_trailing_zeros_from_str(s):
    return s.replace('\x00', '')


def calculate_note(notes):
    if notes == 255:
        return 'None'
    notes_from_c = notes // 8
    scale_num = int(notes_from_c // len(NOTE_SCALE))
    note = NOTE_SCALE[notes_from_c % len(NOTE_SCALE)]
    return note + str(scale_num)


class NoteInfo:

    def __init__(self, bytes):
        self.sample_num = bytes[0]  # First 2 bytes refer to the sample number, typically < 31
        self.second_byte = bytes[2:4]  # number of notes after C0 * 8 (8 samples per note)
        self.note_played = calculate_note(self.second_byte[0])
        self.note_played_raw = self.second_byte[0] // 8 + 24
        # C0 starts at 12 for MIDI, add 12 to it to make it "midi compliant"
        self.note_played_midi = self.note_played_raw + 12
        self.third_byte = bytes[4:]
    
    def __str__(self):
        return f"SampleNum: {self.sample_num}, Note: {self.note_played}, ThirdByte: {self.third_byte.hex()}"

class Sample:
    def __init__(self, sname, stype, ssize, siden, sloops, sloope, edata, snume):
        self.sname = sname
        self.stype = stype
        self.ssize = ssize
        self.siden = siden
        # NDS7 - SOUNDxPNT - Sound Channel X Loopstart Register (W)
        self.sloops = sloops
        self.sloope = sloope
        self.edata = edata
        self.snume = snume
        # Assume its a one shot if no loop start is given (?)
        self.type = 1 if sloops else 2
    
    def __str__(self):
        s = [f"Sample Name: {self.sname}",
             f"Type: {self.stype}",
             f"Size: {self.ssize} bytes",
             f"Start Note: {hex(self.siden)}",
             f"Loop start: {self.sloops}",
             f"Loop end: {self.sloope}",
             f'Section num: {self.snume}',
             f'Type: {"one shot" if self.type == 2 else "loop"}']
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
    header = "0000|1111|2222|3333|4444|5555|6666|7777|8888|9999|AAAA|BBBB|CCCC|DDDD|EEEE|FFFF\n" + "-"*79
    contents = []
    for x in seq_info:
        # split into 4s to add the barrier between
        split_thing = []
        for i in range(len(x)//4):
            split_thing.append(''.join([str(y.sample_num) for y in x[i*4:(i+1)*4]]))
        contents.append('|'.join(split_thing))
        for y in x:
            print(y)
        print('')
    print(header)
    for c in contents:
        print(c)
    print('')


def generate_midi_tracks(seq_info):
    # Create a new MIDI file for it ! yayy...
    # len(seq_info) = number of channels in there
    for c_num, channel in enumerate(seq_info):
        mf = MIDIFile(len(seq_info))
        track = 0
        time = 0  # start at beginning
        mf.addTrackName(track, time, f"MIDI_Ch_{c_num}")
        # TODO: Get the BPM somehow too
        mf.addTempo(track, time, 120)
        # go through each note and add the note info to the sequence!
        for n_index, note in enumerate(channel):
            if note.note_played == 'None':
                continue
            pitch = note.note_played_raw
            print(pitch)
            duration = 1  # 1 beat long
            time = n_index/4  # when the note strikes... split into quarters
            volume = 127  # TODO: Figure out the volume stuff in a bit
            mf.addNote(0, c_num, pitch, time, duration, volume)
        with open(f"{c_num}.midi", "wb") as f:
            mf.writeFile(f)
    

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
                note_obj = NoteInfo(notes_file.read(6))
                if seq_info[channel] == None:
                    seq_info[channel] = [note_obj]
                else:
                    seq_info[channel].append(note_obj)
        display_seq_info(seq_info)
    return seq_info


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
    seq_info = get_note_info(VF, num_channels)
    generate_midi_tracks(seq_info)
    # calculate the end
    len_tracks = VF.size - 0x774
    section_size = 6 * num_channels * 64
    return len_tracks, num_samples, order

def main():
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
            "Seqs": seqs[2:],
            "CalcNumSeqs": tracklen/section_size
        }})
    print(json.dumps(data, indent=4))

main()
