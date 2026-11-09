"""Short hardware headings, with full names retained in the editor and DSP ABI."""
PEDAL_NAMES={
 'Tonic':{'Amount':'Amnt'},
 'Arrakis':{'Detune':'Detun'},
 'Dissolve':{'Chance':'Chnce','Glitch':'Gltch'},
 'Dustbox':{'Filter':'Filt'},
 'Galactic':{'Replace':'Repl','Bright':'Brght','Detune':'Detun','Bigness':'Size'},
 'Howl':{'Annihil':'Anhil'},
 'Mangle':{'Feedbk':'Feed','Tremolo':'Trem'},
 'Oxide':{'Flutter':'Flutr','FlutSpd':'FlSpd','HeadBmp':'HBump','Output':'Out'},
 'Shatter':{'Chance':'Chnce'},
 'Spiral':{'Feedbk':'Feed'},
 'Spool':{'Flutter':'Flutr','Spring':'Sprng'},
 'Stasis':{'Length':'Len','Capture':'Capt'},
 'Taffy':{'Chance':'Chnce'},
}
def pedal_name(effect,name):return PEDAL_NAMES.get(effect,{}).get(name,name)
def restore_names(effect,params):
 reverse={short:full for full,short in PEDAL_NAMES.get(effect,{}).items()}
 for p in params:p['name']=reverse.get(p['name'],p['name'])
 return params
