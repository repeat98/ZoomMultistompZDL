/* Runs one cab fit off the page's main thread (a fit takes several seconds). */
importScripts('cab_loader.js');
onmessage = ({data}) => {
  try {
    const wav = CabLoader.parseWav(data.buffer);
    const f = CabLoader.fit(CabLoader.prepare(wav));
    postMessage({ok: true, id: data.id, cab: {fir: f.fir, sos: f.sos, gain: f.gain, errorDb: f.errorDb,
      worstDb: f.worstDb, sourceMs: f.sourceMs, sourceRate: wav.sampleRate, plot: f.plot}});
  } catch (e) {
    postMessage({ok: false, id: data.id, error: e.message});
  }
};
