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
SAMPLE_STRUCT_FORMAT = "<22sHIIIII"
SAMPLE_STRUCT = struct.Struct(SAMPLE_STRUCT_FORMAT)

NOTE_SCALE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# 0..127 L..R
# Panning is fixed for the first 12 channels (music channels)
PANNING = [ 0, 127, 127, 0, 0, 127, 127, 0, 0, 127, 127, 0, 0, 127, 127, 0 ]
EMPTY_NOTE = '--'


def calculate_volume(byte):
    if byte == 0:
        return 0
    return (byte-1)*2


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

    def __init__(self, bytes, samples):
        self.start_volume = 0
        self.sample_used = None
        self.volume = 0
        self.sample_num = bytes[0]+(bytes[1]*16) if bytes[0] != 0 else EMPTY_NOTE  # First 2 bytes refer to the sample number, typically < 31
        if self.sample_num != EMPTY_NOTE and samples[self.sample_num-1] is not None:
            self.sample_used = samples[self.sample_num-1]
            self.start_volume = self.sample_used.volume

        self.second_byte = bytes[2:4]  # number of notes after C0 * 8 (8 samples per note)
        self.note_played = calculate_note(self.second_byte[0])
        self.retrigger = self.second_byte[1] == 1  # retriggers the same
        self.note_played_raw = self.second_byte[0] // 8 + 12
        # C0 starts at 12 for MIDI, add 12 to it to make it "midi compliant"
        self.note_played_midi = self.note_played_raw + 12
        self.third_byte = bytes[4:]
        if bytes[4] == 12:
            self.volume = calculate_volume(bytes[5])
        elif self.sample_num != EMPTY_NOTE or self.retrigger:
            # Then set to the original volume
            self.volume = self.start_volume
        if bytes[4] == 15:
            print(f'Found this: {bytes[5]}')
    
    def __str__(self):
        return f"SampleNum: {self.sample_num}, Note: {self.note_played}, Volume: {self.volume}, TB: {self.third_byte}"

class Sample:
    def __init__(self, sname, ssize, volume, sloops, sloope, snume):
        self.sname = sname
        self.ssize = ssize
        self.volume = calculate_volume(volume)
        # NDS7 - SOUNDxPNT - Sound Channel X Loopstart Register (W)
        self.sloops = sloops
        self.sloope = sloope
        self.snume = snume
        # Assume its a one shot if no loop start is given (?)
        self.type = 1 if sloops else 2
    
    def __str__(self):
        s = [f"Sample Name: {self.sname}",
             f"Size: {self.ssize} bytes",
             f"Volume: {self.volume}",
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
    # Skip title
    VF_sample_info.read(0x14)
    # Read sample information
    next_session = False
    for i in range(31):
        # get a section of data
        sample_struct = VF_sample_info.read(SAMPLE_STRUCT_SIZE)
        sample_name, idk_yet, sample_size, sample_iden, sample_loop_start, sample_loop_end, _ = SAMPLE_STRUCT.unpack(sample_struct)
        sample_name_decoded = sample_name.decode('utf8')
        if '.pcm' not in sample_name_decoded:
            continue
        # First 24 bytes are the the sample name, which is loaded in from /music/%s
        sample_name = remove_trailing_zeros_from_str(sample_name_decoded)
        s = Sample(sample_name, sample_size, sample_iden, sample_loop_start, sample_loop_end, i+1)
        samples[i] = s
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
    num_sequences = sequences[1]
    sequences = sequences[2:]
    return num_channels, sequences, num_sequences


def display_seq_info(seq_info):
    header = "#| 0 0 0 0 |1 1 1 1 |2 2 2 2 |3 3 3 3 |4 4 4 4 |5 5 5 5 |6 6 6 6 |7 7 7 7 |8 8 8 8 |9 9 9 9 |A A A A |B B B B |C C C C |D D D D |E E E E |F F F F\n" + "-"*146
    contents = []
    for xnum, x in enumerate(seq_info):
        # split into 4s to add the barrier between
        split_thing = []
        volume_thing = []
        for i in range(len(x)//4):
            split_thing.append(''.join(['R ' if y.retrigger else str(y.sample_num)+' '*(2-len(str(y.sample_num))) for y in x[i*4:(i+1)*4]]))
            # volume_thing.append(''.join([str(y.volume) for y in x[i*4:(i+1)*4]]))
        contents.append('|'.join(split_thing))
        # contents.append('|'.join(volume_thing))
        # print(f"[+]  Section #{xnum}")
        # for y in x:
        #     print(f'  {y}')
        # print('')
    print(header)
    for cnum, c in enumerate(contents):
        print(f"{hex(cnum)[2:]}| {c}")
    print('')


def test_me(seq_info):
    for i in range(len(seq_info)):
        for c_num, channel in enumerate(seq_info[i]):
            unique_samples = []
            for n_index, note in enumerate(channel):
                if note.sample_used is not None and note.sample_used not in unique_samples:
                    unique_samples.append(note.sample_used)
            if len(unique_samples) > 1:
                print(f"[!]  Seq @: {i}.{c_num+1}; contains multiple samples: {unique_samples}")


def generate_midi_tracks(seq_info, order, output_filename):
    # Create a new MIDI file for it ! yayy...
    num_channels = len(seq_info[0])
    mf = MIDIFile(num_channels)
    # TODO: Get the BPM somehow too
    time = 0  # start at beginning
    mf.addTempo(0, time, 120)
    # TODO: Make separate channels for these weird MIDI channels that change samples... really annoying
    for i in range(num_channels):
        mf.addTrackName(i, time, f"MIDI_Ch_{i}")
    for cur_time, i in enumerate(order):
        for c_num, channel in enumerate(seq_info[i]):
            # TODO: These dont work, lol
            mf.addControllerEvent(c_num, c_num, time, 10, PANNING[c_num])
            # go through each note and add the note info to the sequence!
            for n_index, note in enumerate(channel):
                if note.note_played == 'None':
                    # Will set the volume of an already played note if possible
                    if note.third_byte[0] == 12:
                        # TODO: This doesnt work?
                        mf.addControllerEvent(c_num, c_num, time, 7, note.volume)
                    continue
                pitch = note.note_played_raw
                for d_iter, d_note in enumerate(channel[n_index+1:]):
                    if d_note.retrigger or d_note.sample_used is not None:
                        # then we hit the next note, set the duration to that
                        break
                duration = (d_iter+1)/4
                # Look forward until either a new note is played or a retrigger is found OR the end of the sequence (64)
                time = cur_time*16 + (n_index/4)  # when the note strikes... split into quarters
                mf.addNote(c_num, c_num, pitch, time, duration, note.volume)
        time += 16
    with open(f"{output_filename}_{c_num}.midi", "wb") as f:
        mf.writeFile(f)


def get_note_info(vfile, num_channels, samples):

    data_size = vfile.size - SEQ_INFO_BYTES - HEADER_BYTES
    notes_file = VirtualFile(vfile.read(data_size))

    # 6 = length of the struct
    # 64 = guessed length of the thingy
    section_size = 6 * num_channels * 64
    num_seqs = int(data_size / section_size)
    notes_per_seq = section_size // 6

    sequences = []
    for i in range(num_seqs):
        seq_info = [None] * num_channels
        # split into 6 byte parts for each thing
        for _ in range(64):
            for channel in range(num_channels):
                note_bytes = notes_file.read(6)
                note_obj = NoteInfo(note_bytes, samples)
                if seq_info[channel] == None:
                    seq_info[channel] = [note_obj]
                else:
                    seq_info[channel].append(note_obj)
        display_seq_info(seq_info)
        sequences.append(seq_info)
    return sequences


def process_mus_file(filename):
    # Remove the .mus at the end
    output_filename = Path(filename).name[:-4]
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
    num_channels, order, nseqs = get_seq_data(VF)
    # Now we get into the track information... 0x774 til end
    seq_info = get_note_info(VF, num_channels, samples)
    # generate_midi_tracks(seq_info, order, output_filename)
    test_me(seq_info)
    # calculate the end
    len_tracks = VF.size - 0x774
    return len_tracks, num_samples, order, num_channels, nseqs

def main():
    data = {}
    for mfile in glob.glob("data/music/credits.mus"):
        filename = Path(mfile).name
        print(f"[+]  Processing {filename}")
        tracklen, nsample, seqs, nchannels, nseqs = process_mus_file(mfile)
        section_size = 6 * nchannels * 64
        data.update({filename: {
            "TrackLen": tracklen,
            "NumSamples": nsample,
            "NumChannels": nchannels,
            "NumSeqs": nseqs,
            "Seqs": seqs
        }})

    print(json.dumps(data, indent=4))

main()
