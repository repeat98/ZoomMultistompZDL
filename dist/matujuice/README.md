# Matujuice Zoom MS ZDL effects pack

Twelve free effects for Zoom MS pedals, made for synths and drum machines.

WaveFold, DualShft, Choral, EuGate, DubSiren, S.GN_L, Scrub, DIRTBOX, Breather, SyncEQ, GridDly and Sweep. Free to use and share (MIT licence, see LICENSE).

Unofficial. Not affiliated with or endorsed by Zoom. Use at your own risk.
Tested on a Zoom MS-60B running MS-50G firmware. The MS-70CDR, MS-50G and other MS pedals are untested, so reports are welcome.

## Install

1. Open **Zoom Effect Manager** and connect the pedal.
2. In Zoom Effect Manager open Settings, choose "Read Effects from folder" and select the folder with the `.ZDL` files. Then turn on "Effects from devices" and "From Folder", add the effects you want and write them to the pedal.

All twelve are mono. The footswitch turns the effect on and off like normal.

## How the knobs work

Every knob shows its real value on the pedal's screen where that makes sense (BPM, milliseconds, note names).

**Tempo knobs hold every BPM twice.** On every effect with a Tempo knob (DualShft, Choral, EuGate, DubSiren, Scrub, GridDly, SyncEQ, Breather, Sweep) it runs 40..240 BPM and then, past 240, shows 40..240 again (a twin copy). Both copies play the same tempo. Jumping from a BPM to its twin (120 to the second 120) restarts the LFO, pattern or grain right away without changing the tempo. That is meant for a MIDI host (an iPhone script, such as [Zoom MS bar sync for Mozaic](https://patchstorage.com/zoom-ms-bar-sync-keep-custom-zoom-effects-on-the-beat/), or a small box) that sends this one knob edit on every downbeat to keep the effect on the bar. By hand, just stay on one copy. Tempo is the 8th knob on all of them, so the host sends the same knob number whatever the effect. While one of these effects is switched off its LFO or pattern keeps running in the background, so it comes back in time (DubSiren needs Trig SHold or SPuls for that, EuGate Reset OFF, NOTE or SYNC).

**Bar sync for slots 4 to 6.** Mozaic can only edit the first three slots. A tempo effect there that Mozaic flips (or SyncEQ) passes each bar on, unheard, to the effects after it. A tempo effect with Tempo all the way down on **FOLLW** follows it: the same bars and BPM (120 until something upstream sends; if the sender goes away it keeps the last BPM). On a BPM it ignores it and runs on its own, so you can mix synced and free effects. Point Mozaic's Send knob at the one effect that sends and put the other synced effects on FOLLW (in slots 1 to 3 too). Effects without a Tempo knob let it through.

### WaveFold: wavefolder
A fold curve from a published Buchla 259 model (Esqueda, Pontynen, Valimaki and Parker, DAFx-2017). Five parallel folding stages bend the sound back on itself as Drive goes up. The loudness is matched to your input automatically. No oversampling, so high notes at high Drive alias.

| Knob | Range | What it does |
|---|---|---|
| Drive | 0..100 | How hard the signal is pushed into the folder. Higher = more folds. |
| Symm | -50..+50 | 0 is symmetric. Away from 0 adds even harmonics. |
| Tone | 0..100 | Low-pass after the fold, about 200 Hz up to open. |
| Level | 0..100 | 50 = wet matches the input loudness, 100 = +6 dB. |
| Mix | 0..100 | Dry/wet crossfade, DJ style: the dry sound stays full up to 50, the effect is full from 50, so at 50 both play at full level. |

### DualShft: tempo-synced dual pitch shifter
Two pitch-shift voices, each with its own echo time, plus one tempo-synced LFO that bends them in opposite directions. No feedback.

| Knob | Range | What it does |
|---|---|---|
| Ptch1 / Ptch2 | -24..+24 semitones | Pitch of each voice, with tenths of a semitone around 0. |
| Dly1 / Dly2 | 12 ms..1 s, note values | Echo time of each voice. The top of the knob syncs to Tempo as note values (1/32 .. 1 bar). A synced time too long for the 3.9 s buffer is halved (1 bar below about 62 BPM). |
| Div | 4 bars .. 1/64 | Length of one LFO cycle (dotted and triplet values included). |
| Depth | 0..12 semitones | How far the LFO bends the pitch. 0 = no LFO. |
| Shape | Tri, Sqr, Rand, Step, Sine, Rise, Fall | LFO shape. |
| Tempo | FOLLW, 40..240 BPM, twice | Tempo for the LFO. Changing it only changes the LFO speed; the second copy of the same BPM restarts the LFO (see above). |
| Mix | 0..100 | Dry/wet crossfade, DJ style: the dry sound stays full up to 50, the effect is full from 50, so at 50 both play at full level. |

### Choral: choir
Listens to the note your synth plays and sings it with its own choir, so every synth (bright saw, sine, closed filter) gets the same voice. For mono lines: leads, basses, arps. A chord or a pad has no single note, so the choir drops out and only the dry synth plays. A new note is found in about 10 to 70 ms, octave jumps included, and fast arps (16ths at 160 BPM) are followed note by note: at Glide 0 a legato change hushes the old note and starts the new one fresh. Two detuned oscillators work too: when they drift in and out of phase and look like an octave or a fifth up, the choir waits 3 s before it believes it (a real octave jump is still taken at once). In a decay tail the choir keeps its note. Breath noise follows the singers' own level, so it stays well under the voice on high notes and high sections too.

| Knob | Range | What it does |
|---|---|---|
| Choir | MEN, WOMEN, KIDS, GIANT, M+W, M+KID, W+KID, G+M, G+W, G+KID, M+W+K, G+M+W, G+M+K, G+W+K, ALL, MONKS, GOSPL | Who sings: every combination of the four sections, then two characters: MONKS (men and giants, straight tone with no vibrato, dark) and GOSPL (men and women, wide vibrato, bright, breathy). MEN on your note, WOMEN an octave up, KIDS two up, GIANT one down; each section has its own throat, breath and vibrato. |
| Size | SOLO, DUO, TRIO, QUART, QUINT, SEXT | How many singers (1..6). A bigger choir is looser in timing and tuning. |
| Chord | UNIS, +1 .. +11, OCT, MAJ, MIN, SUS2, SUS4, DIM, AUG, MAJ7, MIN7, DOM7, ADD9, OPEN, DRONE | How they sing together. UNIS: all on your note. +1 to +11 and OCT: every second singer that many semitones (piano keys) up, from rubbing (+1, +2) to sweet (+3, +4), open (+5, +7) and the octave (OCT = +12). Chords: the singers take the chord's tones in order, so DUO sings root and 3rd, TRIO the triad, more singers add the octave and more. OPEN is root, 5th and 10th. DRONE: every second singer holds the first note of the phrase while the others follow you. The same shape on every note (no key). |
| Sing | AAH, EHH, EEE, OHH, OOH, MMM, OOAH, VOWL, LA, DOO, SWELL, CANON | What they sing. The first six are one vowel (MMM is a hum). OOAH opens from "oo" to "ah" and back once per Pace cycle; VOWL steps A E I O U, one per Pace cycle. LA and DOO sing a syllable once on every note: LA opens from "l" to "ah", DOO starts with a short stop and closes from "eh" to "oo"; Pace sets how long that takes (1/64 is a quick "la", 1bar a slow opening). SWELL: the choir breathes in and out once per Pace cycle. CANON: each section comes in one Pace cycle after the one before and sings what you played that much earlier (a round; one cycle can be at most 1 s). |
| Pace | 4bar .. 1/64 | Length of one cycle of the movement. |
| Feel | 0..100 | 0 = soft and legato (slow attack, wide vibrato, breathy, dark) .. 100 = punchy and staccato (fast attack and release, bright, OOAH snaps). |
| Glide | 0..100 | 0 = every note starts fresh, even when you play legato (best for fast arps). 1..100 = legato: the voice keeps singing and slides to the new note, ~3 ms .. ~0.6 s. |
| Tempo | FOLLW, 40..240 BPM, twice | Tempo for Pace. Changing it only changes the speed; the second copy of the same BPM marks a downbeat (see above), and the movement lands where it should be after that many bars, so a 2-bar or dotted Pace is never cut. |
| Mix | 0..100 | Dry synth / choir crossfade, DJ style: the dry sound stays full up to 50, the choir is full from 50, so at 50 both play at full level. |

### EuGate: Euclidean rhythm gate
Chops the sound into a repeating rhythm. Every step is a 16th note. Notes are spread as evenly as possible over the steps (a Euclidean rhythm).

| Knob | Range | What it does |
|---|---|---|
| Notes | 1..64 | How many notes play. At or above Steps = every step. |
| Steps | 1..64 | Pattern length. Anything other than 16, 32 or 64 runs against the bar: polymeters. |
| Shift | 0..63 | Starts the pattern later by this many steps. |
| Swing | 0..100 | Delays only the weak 16ths. |
| Reset | OFF, NOTE, PEDAL, SYNC | What restarts the pattern: nothing, every new note after silence, or turning the effect on. SYNC is the setting for bar sync from a host: the same as OFF, only the host's restarts count. |
| Gap | 0..50 % of a step | Small silence at the end of a note that is followed by another note. |
| Soft | 0..100 | Softness of the note edges. 0 = hard chop. |
| Tempo | FOLLW, 40..240 BPM, twice | Tempo. Jumping to the second copy of the same BPM restarts the pattern at step 1 (see above). |
| Mix | 0..100 | Dry/wet crossfade, DJ style: the dry sound stays full up to 50, the effect is full from 50, so at 50 both play at full level. The gaps are silent in the wet sound. |

Try 5 notes in 16 steps (the default), then 7 in 12 or 5 in 12 for a different feel.

### DubSiren: dub siren with tape echo
A siren oscillator with LFO modes, played from the footswitch, into its own tape-style echo. Your input passes through untouched.

| Knob | Range | What it does |
|---|---|---|
| Trig | Hold / Pulse / SHold / SPuls | Hold = sounds while the effect is on. Pulse = one short burst each time you turn it on. SHold and SPuls do the same on the beat: the siren waits for the next beat of the Tempo clock (re-aligned by each twin flip from a host) and the siren tones stay in step with the bar. |
| Mode | Wail, Fast, Slow, Laser | LFO shape. Fast is twice the Rate, Slow is half. |
| Pitch | 110 Hz..1760 Hz | Base pitch. |
| Rate | Man, 0.15..15 Hz, note values | LFO speed. The top of the knob syncs to Tempo as note values (4 bars .. 1/32). |
| Depth | 0..100 | How far the LFO sweeps the pitch. |
| Vol | 0..100 | Siren level. |
| Time | 50 ms..1 s | Echo time (never synced). |
| Tempo | FOLLW, 40..240 BPM, twice | Used when Rate is set to a note value and by SHold / SPuls. Jumping to the second copy of the same BPM restarts the LFO (see above). |
| Fdbk | 0..125 | Echo repeats. 0 = no echo, above 100 it self-oscillates. |

### S.GN_L: broken digital line
The sound is cut into packets and some of them never arrive, like a VoIP call on bad Wi-Fi or a digital radio losing lock. What fills the hole is most of the character: silence, the last packet replayed as a buzz or a stutter, a fading replay, or hiss. A Codec knob wrecks the quality on top (spectral holes, a closing low-pass, a lower sample rate, fewer bits). The file is `SGNL.ZDL`; the pedal shows the name S.GN_L.

| Knob | Range | What it does |
|---|---|---|
| Loss | 0..100 | How many packets are lost. 0 = clean line, 100 = about 85 %. |
| Size | 1 ms..500 ms | Packet length. Short = grit and, with REPT, a buzz at the packet rate (5 ms = about 200 Hz). Long = notes and words drop out or stutter. |
| Codec | 0..100 | Codec quality going down. Above 50 the first packet after a silence is lost too, like a call clipping the start of a word. |
| Fill | GAP, REPT, FADE, NOISE, REVRS, GARBL, LATE, RND | What replaces a lost packet: silence, the last packet replayed, the replay dying away, hiss at the level of the sound, the last packet backwards, corrupted data (boosted random slices, a digital screech), an older packet out of order so phrases shuffle, or a random one of these per outage (never GARBL). |
| Burst | 0..100 | 0 = scattered single losses, 100 = long outages, with the same overall amount. |
| Jump | 0..100 | How often the quality suddenly drops for a few packets and comes back. |
| Line | HIFI, VOIP, PHONE, WALKY | Band of the line: full and untouched, 200 Hz..5 kHz with a steep low cut and a boxy headset bump at 1.5 kHz, 300 Hz..3.4 kHz, or 500 Hz..2.5 kHz with some drive. |
| Edge | 0..100 | Cut at the packet edges. 0 = hard clicks, 100 = fades that fill most of the packet, so lost packets become soft dips and swells (longer with bigger Size). |
| Mix | 0..100 | Dry/wet crossfade, DJ style: dry full up to 50, wet full from 50, both full at 50. |

Try Size 5 ms with Fill REPT and Burst high for robot voice, or Size 60 ms, Fill GAP and Line PHONE for a bad call.

### Scrub: scrub through the past, freeze where you stop
Everything you play is recorded into a 7.9 second buffer. Pos moves a read head through it: turning it, short grains follow the head through the audio at the original pitch, and when you stop, the grain just before the head loops on and on, crossfaded so the loop has no click. Known from Mutable Instruments Clouds/Beads (Position + Freeze) and the Morphagene.

| Knob | Range | What it does |
|---|---|---|
| Pos | 6.00 s..0 ms back | Where the head is in the last 6 seconds, in 10 ms steps (600 steps). The screen shows how far back it is; 0ms is the present (in HOLD, the moment you froze). |
| Grain | 10 ms..1 s, then 1/64..1/2 | Length of the loop. Short = a buzzing tone made of the sound, long = a whole hit or chord repeating. Past 1 s come note values synced to Tempo (1/64, 1/32, 1/16T, 1/16, 1/8T, 1/16., 1/8, 1/4T, 1/8., 1/4, 1/4., 1/2), so the freeze loops in time with the song. Long grains pull the head in so the whole grain still fits in the buffer: a synced grain over about 1 s, or with Dir REV, PING or RAND in LIVE any grain over about 0.6 s (a backward grain in LIVE reads further back, because the recording moves on under it). A synced grain too long to fit even at 0ms (1/2 below about 55 BPM, backward in LIVE) is shortened. |
| Rec | LIVE, HOLD, STOMP | LIVE keeps recording, so Pos is how far back you listen: a delay you can sweep. HOLD stops recording and Pos scrubs the last 6 of the 7.9 seconds kept. STOMP records while the effect is switched off and freezes the moment you switch it on (needs the pedal to pass the sound through a switched-off effect; if ON gives silence, use LIVE and HOLD). |
| Glide | 0..100 | How slowly the head follows Pos. 0 = it jumps, 40 = about 0.1 s, 100 = about 3 s, a slow glide. It also hides the knob's steps. |
| Dir | FWD, REV, PING, RAND | Which way the grain plays: forward, backward, ping-pong (forward then backward in turns) or random (each grain flips a coin). PING turns round on itself, so the loop has no jump and sounds smoother and more tonal. |
| Spray | OFF, +-1..+-250 | Random offset for each new grain, either side of the head, shown in ms (+-250 = up to 250 ms before or after; never ahead of now): a moving cloud instead of a steady loop. |
| Mix | 0..100 | Dry/wet crossfade, DJ style: dry full up to 50, wet full from 50, both full at 50. |
| Tempo | FOLLW, 40..240 BPM, twice | Only for the synced Grain values. The pedal gives custom effects no clock, so dial in your song's tempo, as on DubSiren. Jumping to the second copy of the same BPM starts a new grain at once (see above). |

Try: play a Digitakt loop in LIVE, turn Rec to HOLD, then sweep Pos slowly with Glide around 60 and stop on a snare. Grain 10..30 ms on a held synth chord gives a buzzy drone; Spray 30 makes it a cloud.

### GridDly: one tempo-synced delay, six engines
New, not in a release yet: built and tested on the MS-60B (2026-10-07).

One mono delay with a 7.9 second memory. Type picks the engine, Time sets the echo (free or a note value at Tempo), and Char changes what it means with each engine.

| Knob | Range | What it does |
|---|---|---|
| Type | DIGI, TAPE, DUB, REVRS, TAPS, LOFI | DIGI: clean repeats. TAPE: wobbly, darker, slightly saturated, and a Time or Tempo change glides the pitch like tape. DUB: band-limited, saturated repeats, the dirtiest drone above Fdbk 100. REVRS: each chunk of Time plays backwards; chunks start on the bar with bar sync. TAPS: three echoes inside Time, each quieter. LOFI: every repeat loses bits and sample rate, so it crumbles more each time. |
| Time | 12 ms..1.00 s, then 1/32..1bar, 2bar | Free time on the first 100 steps (as DualShft), then note values at Tempo: 1/32, 1/16T, 1/16, 1/8T, 1/16., 1/8, 1/4T, 1/8., 1/4, 1/4., 1/2, 1bar, 2bar. A time too long for the memory is halved (2bar below about 61 BPM; REVRS needs twice the time, so 1bar below about 61 BPM). Away from TAPE, a Time change crossfades with no pitch bend. |
| Fdbk | 0..120 | How many repeats. 100 = 1:1 into the loop: the repeats only fade by what the engine's filters take (DUB fastest). Above 100 they grow into a drone, DUB too at any Tone. |
| Tone | 0..100 | Dark to bright repeats. On DUB it moves the whole band up (thin and nasal at 100). |
| Char | 0..100 | DIGI: slight chorus on the repeats. TAPE: wow and flutter depth. DUB: drive. REVRS: the fade at each chunk's edges, choppy at 0, smooth at 100. TAPS: the pattern (0..24: 1/4, 1/2, 1 of Time; 25..49: 3/8, 3/4, 1; 50..74: 1/3, 2/3, 1; 75..100: 1/2, 3/4, 1). LOFI: crush, from 12 bits to 4 bits and 1/8 of the sample rate. |
| Duck | 0..100 | The repeats dip while you play and swell back in the gaps. 0 = off. |
| Mix | 0..100 | Dry/wet crossfade, DJ style: dry full up to 50, wet full from 50, both full at 50. |
| Tempo | FOLLW, 40..240 BPM, twice | BPM for the synced Time values. Jumping to the second copy of the same BPM restarts the REVRS chunk on the bar (used by the iPhone bar sync). |
| Tail | OFF, ON | When you switch the effect off: ON lets the repeats ring out and fade, like the stock delays; OFF stops them at once. The dry sound passes untouched either way. |

Try: DUB at 1/8., Fdbk 85, Char 60, then sweep Tone for dub throws on a snare. REVRS at 1bar with bar sync on a pad. TAPS with Char 50 on hats for a triplet trail.

### SyncEQ: EQ that passes the bar sync on
The iPhone bar sync ([Mozaic script v3](https://github.com/matujuice/zoom-ms-zdl-effects-pack/tree/main/tools/mozaic)) can only reach slots 1 to 3. SyncEQ, placed in one of those slots with Mozaic's Send knob pointing at it, marks every bar in a part of the pedal's signal path that the output ignores, so the synced effects after it on FOLLW, even in slots 4 to 6, stay on the bar. Any tempo effect of the pack in slots 1 to 3 sends the same mark, so SyncEQ is only needed when none sits there. Like the tempo effects, it sends only while Mozaic is flipping its Tempo. Switched off, the sound passes untouched and the bar still goes through. The sound side is a clean EQ: with every knob at its default nothing changes.

| Knob | Range | What it does |
|---|---|---|
| LoCut | OFF, 20..500 Hz | High-pass filter, 12 dB per octave. |
| Low | -12..+12 dB | Bass shelf at 100 Hz. |
| Mid | -12..+12 dB | Bell at MidF. |
| MidF | 200..5.0k Hz | Frequency of the Mid bell. |
| High | -12..+12 dB | Treble shelf at 8 kHz. |
| HiCut | 1.0k..20k Hz, OFF | Low-pass filter, 12 dB per octave. |
| Drive | 0..100 | Soft saturation after the EQ. 0 = clean; the output is turned down as Drive goes up. |
| Tempo | 40..240 BPM, twice | The BPM passed on with each bar. Mozaic flips it between a BPM and its twin copy on each downbeat; each flip marks a new bar. |
| Level | -12..+12 dB | Output level. |

### Breather: tempo-synced pump with a reverb
On every beat (or every Div) something moves: your sound, the built-in reverb, both, or what goes into the reverb. Targt picks what, Shape picks how. Made for pads, basses, percussion and drum machines around 160 BPM.

| Knob | Range | What it does |
|---|---|---|
| Targt | DRY, VERB, BOTH, SEND | What moves. DRY = your sound (the reverb stays steady). VERB = only the reverb; your sound passes untouched. BOTH = both together. SEND = what goes into the reverb: your sound is untouched and the tail rings out freely. |
| Shape | DUCK, GATE, RISE | How it moves, starting on the downbeat. DUCK drops on the beat and comes back (classic sidechain pump). GATE cuts on the beat, stays cut for Curve, then opens (a hard duck). RISE is quiet after the beat, grows into the next one and drops on it. |
| Depth | 0..100 | How far the level moves. 100 = all the way to silence. |
| Div | 1/16, 1/8, 1/4, 1/2, BAR | How often it fires. |
| Shift | 0..100 % of a beat | Moves the whole pump later: +1/16 at 25, +1/8 (the offbeat) at 50, +3/16 at 75, +1/4 at 100. Small values nudge it onto the body of the kick. At 50 the sound is loudest on the kick and dips in between. |
| Curve | 0..100 | How long each move lasts, 5 % to 100 % of the Div: the recovery for DUCK, how long GATE stays cut, how long RISE grows. |
| Verb | 0..100 | Reverb level. 0 = no reverb, a pure pump. |
| Tempo | FOLLW, 40..240 BPM, twice | Tempo. Jumping to the second copy of the same BPM restarts the pump on beat 1. FOLLW (the bottom of the knob) follows the bar sync sent by an effect in an earlier slot: its BPM (120 until one is heard, the last one kept if the sender goes away) and its bars, each restarting the pump on beat 1. On a BPM it ignores that and runs on its own. In slots 1-3, FOLLW needs that slot's Mozaic pad off. |
| Size | 0..100 | Reverb length, from a short room to a long wash. Bigger is also darker. |

No Mix knob: Depth and Verb already set how much you hear. Out of the box it is a sidechain pump on your sound and the reverb together (BOTH + DUCK, Depth 80, 1/4, Verb 35). Switched off, the input passes untouched but the beat clock keeps running, so the pump comes back on the bar. Switching it on restarts it on the one, unless the iPhone bar sync has sent a restart in the last 8 seconds.

Try: DRY + DUCK on a pad (the classic pump); DRY + GATE (hard pump: silent on the kick, back after Curve); VERB + RISE (the reverb swells into every kick); SEND + GATE (the hits stay dry, the gaps wash out); DRY + GATE with Shift 50 and Curve 50 (open on the beat, cut on the offbeat: a chop).

### DIRTBOX: a distortion box for an acid machine
Made for a TB-303 / TD-3 (or a MeeBlip triode) going into the pedal: seven real distortion pedals on the Model knob, mildest first, a 3-band EQ voiced for acid, and an automatic noise reducer (ZNR). Same fxid 491 as the first 3-model DirtBox. Drive mostly adds dirt rather than volume: an input peaking around -14 dBFS comes out at about the same level at any Drive.

Each model follows the real circuit stage by stage, from a published analysis or a circuit-level digital model (filters evaluated at 44.1 kHz, diode and transistor curves fitted to the model's):

- **TS9**: Ibanez TS9 Tube Screamer, after guitarix's [ts9sim](https://github.com/brummer10/guitarix/blob/master/trunk/src/plugins/ts9sim.dsp): gain only above 720 Hz, the 1N914s soft-clipping in the feedback, the 723 Hz low-pass with the treble control. The mid-hump overdrive.
- **DIST+**: MXR Distortion+, after the ElectroSmash analysis and guitarix's [mxrdist](https://github.com/brummer10/guitarix/blob/master/trunk/src/LV2/faust/mxrdist.dsp): 741 gain up to 214x, the 741's limited bandwidth, germanium diodes. The pedal has no tone knob, so Tone is a gentle low-pass.
- **DS-1**: the distortion built into the Behringer TD-3, a copy of the Boss DS-1 ([ElectroSmash](https://www.electrosmash.com/boss-ds1-analysis), [DS1.lv2](https://github.com/LiamLombard/DS1.lv2)): 35 dB booster, op-amp stage, 1N4148s, the DS-1 tone.
- **RAT2**: ProCo RAT 2 (same gain stage and clipper as the RAT), after the [Proco-Rat nodal model](https://github.com/Rudro085/Proco-Rat): two gain legs, the LM308's treble loss as gain rises, 1N914s, the Filter.
- **MUFF**: Big Muff Pi, guitarix's [bmp](https://github.com/brummer10/guitarix/blob/master/trunk/src/LV2/faust/bmp.dsp) circuit model: two transistor clipping stages and the Big Muff tone stack (noon = the mid scoop). Drive = Sustain. The Muff's input booster (about +24 dB), which bmp leaves out, is added back, so it saturates at synth levels like the real pedal.
- **SFUZZ**: Univox Super-Fuzz, from the schematic (no circuit-level digital model was found): high-gain preamp, the push-push doubler (octave up), germanium diodes. Tone = the Tone switch made continuous: 0 = the 1 kHz scoop fully in (fat and bassy), 100 = off. Drive = Expander.
- **MT-2**: Boss MT-2 Metal Zone, guitarix's [MetalTone](https://github.com/brummer10/MetalTone) circuit model: +25 dB mid pre-filter, Dist stage, the clipper, the post filter. Tone = the High knob.

Only RAT2 is nearly clean at Drive 0; the others still distort at 0, as the real pedals do. No oversampling, so high notes at full Drive alias a little.

| Knob | Range | What it does |
|---|---|---|
| Model | TS9, DIST+, DS-1, RAT2, MUFF, SFUZZ, MT-2 | Which pedal, mildest first. Default RAT2. Switching fades the effect back in over a few ms so it doesn't click. |
| Drive | 0..100 | The pedal's own gain knob (Drive, Distortion, Dist, Sustain, Expander). |
| Tone | 0..100 | The pedal's tone control, 100 = brightest. Default 80. |
| Low | -12..+12 dB | Shelf at 110 Hz: the 303's body. 0 = flat (default). |
| Mid | -12..+12 dB | Peak at 1 kHz: the squelch of the resonance. 0 = flat (default). |
| High | -12..+12 dB | Shelf at 4.5 kHz: the fizz. 0 = flat (default). |
| ZNR | 0..100 | Noise reducer on the distorted sound only. It measures your noise floor by itself and stays shut this far above it: +9 dB at 1, +19.5 dB at 50, +30 dB at 100. 0 = off. |
| Level | 0..100 | Distorted level, 50 = about the input level, 100 = +6 dB. |
| Mix | 0..100 | Dry/wet crossfade, DJ style: dry full up to 50, wet full from 50, both full at 50 (parallel distortion). |

**ZNR for acid lines.** It listens to the clean input, not the distorted sound, so it follows each note's real decay. The noise floor it measures can never be set above -60 dBFS, so the threshold never climbs into the music. Below the threshold it waits 30 ms, then turns the distortion down firmly (a 1:5 expander, which takes hiss down by about 75 dB at ZNR 50) over about 80 ms: quick enough to clear the hiss in a rest between 16ths at 140 BPM, while a note's tail still fades the way it does on the input. More gain means more hiss to clear; turning ZNR up cuts more.

Try: TD-3 into RAT2 at Drive 50, Tone 80, Mid +3 for a classic squelch; DS-1 for the TD-3's own distortion sound; SFUZZ with Tone 0 and Low +4 for fat, octave-up drones; Mix 50 to keep the clean line under the dirt.

### Sweep: phaser, flanger and filter in one
One tempo-locked LFO sweeps one of three engines, picked with Type. Meant for synths and drum machines.

| Knob | Range | What it does |
|---|---|---|
| Type | PH 4, PH 8, FL +, FL -, LP, BP, HP, NTCH | The engine. PH 4 / PH 8: phaser with 4 or 8 all-pass stages (2 or 4 notches). FL +: flanger. FL -: flanger with negative feedback, hollow and metallic. LP / BP / HP / NTCH: resonant low-pass, band-pass, high-pass, notch. |
| Rate | 0.05..8 Hz, then 8BAR, 7BAR .. 2BAR, 1.5B, 1BAR, 3/4, 1/2, 1/4, 1/8, 1/16, 1/32 | The knob goes faster all the way up. Free speed in Hz on the lower part; at the top, one full sweep (up and down) lasts a number of bars or a note value at the Tempo BPM, slowest (8 bars) first, fastest (1/32 note) last. |
| Depth | 0..100 | How far the sweep goes each way around Cntr. 0 = parked, 100 = 2.5 octaves each way. |
| Cntr | 0..100 | Where it sweeps around. Phaser notch and filter cutoff 80 Hz to 10 kHz; flanger delay 8 ms down to 0.3 ms. Higher is brighter for all three. |
| Reso | 0..100 | Feedback (phaser, flanger; the sign comes from Type) or filter resonance. |
| Shape | TRI, SINE, RISE, FALL, SQR, RAND | LFO shape. TRI and SINE start at the centre and rise. RAND glides to a new random height twice per sweep. |
| Tone | 0..100 | Phaser and flanger: how bright the feedback is. Filters: drive into the filter, with the level kept about the same. |
| Tempo | FOLLW, 40..240 BPM, twice | Tempo. A jump to the second copy of the same BPM is a bar: a synced Rate lands where the sweep would be after that bar (a 4 bar sweep is not restarted every bar), a free Rate restarts at the centre. |
| Mix | 0..100 | Dry/wet crossfade, DJ style. The phaser and flanger sound already contains the dry (that is where the notches come from), so 100 is the whole effect. |

Try: LP, Reso 60, Rate 1BAR, Shape RISE on a drum loop for a filter build; PH 8 on a pad with Rate 4BAR; FL - at Reso 70, Cntr 70 for a jet.

## Credits

- Built with the ZoomMultistompZDL toolchain by themanro (https://github.com/themanro/ZoomMultistompZDL).
- WaveFold's curve is from "Virtual Analog Buchla 259 Wavefolder" (Esqueda, Pontynen, Valimaki, Parker; DAFx-2017).
- DIRTBOX's circuit models follow the analyses and open models linked in its section (guitarix, ElectroSmash, DS1.lv2, Proco-Rat, MetalTone).
- The rest is original work.
