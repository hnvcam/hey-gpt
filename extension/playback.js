/* Read browser-maintained counters only. Never read, record, or route audio. */
(() => {
  class PlaybackTracker {
    constructor(){this.previous=null;this.state='unknown';this.updated=0;this.quietSince=null;}
    reset(){this.previous=null;this.state='unknown';this.updated=0;this.quietSince=null;}
    update(row,now){
      const fields=['timestamp','totalAudioEnergy','totalSamplesDuration','packetsReceived',
                    'jitterBufferDelay','jitterBufferEmittedCount'];
      if(!row||fields.some(k=>!Number.isFinite(row[k])||row[k]<0)||
         Math.abs(now-row.timestamp)>2500){this.reset();return;}
      const old=this.previous;this.previous={};
      for(const k of [...fields,'id','audioLevel'])this.previous[k]=row[k];
      const elapsed=old?(row.timestamp-old.timestamp)/1000:0;
      const duration=old?row.totalSamplesDuration-old.totalSamplesDuration:0;
      const energy=old?row.totalAudioEnergy-old.totalAudioEnergy:0;
      const emitted=old?row.jitterBufferEmittedCount-old.jitterBufferEmittedCount:0;
      const delay=old?row.jitterBufferDelay-old.jitterBufferDelay:0;
      const gap=now-this.updated;this.updated=now;
      if(!old||old.id!==row.id||elapsed<=0||elapsed>2.5||gap>2500||duration<=0||
         duration>2.5||energy<0||emitted<=0||delay<0||row.packetsReceived<=old.packetsReceived){
        this.state='unknown';this.quietSince=null;return;
      }
      // Counter deltas include short bursts between polls. The low threshold is
      // independent of speaker volume; text completion cannot override speech.
      const active=energy/duration>1e-8 || (Number.isFinite(row.audioLevel)&&row.audioLevel>0.0001);
      // A large jitter buffer must drain before quiet can be trusted.
      if(active||delay/emitted>0.5){this.state='busy';this.quietSince=null;return;}
      if(this.quietSince===null)this.quietSince=now;
      this.state=now-this.quietSince>=1000?'quiet':'unknown';
    }
    snapshot(now){
      const fresh=now-this.updated>=0&&now-this.updated<2500;
      return {state:fresh?this.state:'unknown',quiet_ms:fresh&&this.state==='quiet'?now-this.quietSince:0};
    }
  }
  if(typeof module==='object'&&module.exports)module.exports=PlaybackTracker;
  else globalThis.heyGPTPlaybackTracker=PlaybackTracker;
})();
