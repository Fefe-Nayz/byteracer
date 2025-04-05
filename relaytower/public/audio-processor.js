// audio-processor.js - AudioWorklet processors for audio handling

// High-quality push-to-talk audio processor
class AudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // For 1-second buffers at 44.1kHz (mono)
    this.sampleRate = 44100;
    this.secondsPerBuffer = 1.0;
    this.bufferSize = Math.floor(this.sampleRate * this.secondsPerBuffer);
    this.buffer = new Float32Array(this.bufferSize);
    this.bufferIndex = 0;
    
    // Voice detection
    this.voiceDetected = false;
    this.silenceThreshold = 0.01;
    this.silentFrameCount = 0;
    this.silentFrameThreshold = 30; // About 600ms of silence to stop
    
    // Track the number of consecutive frames with voice
    this.voiceFrameCount = 0;
    this.voiceFrameThreshold = 5; // To confirm it's not just a spike
    
    // Audio quality settings
    this.gain = 0.0; // Amplification for better volume
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (!input || !input.length || input[0].length === 0) return true;
    
    const inputChannel = input[0];
    
    // Calculate the signal level for this frame
    let maxLevel = 0;
    for (let i = 0; i < inputChannel.length; i++) {
      maxLevel = Math.max(maxLevel, Math.abs(inputChannel[i]));
    }
    
    // Voice detection logic
    if (maxLevel > this.silenceThreshold) {
      this.voiceFrameCount++;
      this.silentFrameCount = 0;
      
      if (this.voiceFrameCount >= this.voiceFrameThreshold) {
        this.voiceDetected = true;
      }
    } else {
      this.voiceFrameCount = 0;
      
      if (this.voiceDetected) {
        this.silentFrameCount++;
        
        if (this.silentFrameCount >= this.silentFrameThreshold) {
          this.voiceDetected = false;
        }
      }
    }
    
    // Copy samples to our buffer if voice is detected
    if (this.voiceDetected) {
      // Apply gain and copy to buffer
      for (let i = 0; i < inputChannel.length; i++) {
        if (this.bufferIndex < this.bufferSize) {
          // Apply gain and soft-clipping
          let sample = inputChannel[i] * this.gain;
          
          // Soft clipper to prevent distortion from gain
          if (sample > 0.8) {
            sample = 0.8 + (sample - 0.8) / (1 + Math.pow(sample - 0.8, 2));
          } else if (sample < -0.8) {
            sample = -0.8 - (Math.abs(sample) - 0.8) / (1 + Math.pow(Math.abs(sample) - 0.8, 2));
          }
          
          this.buffer[this.bufferIndex++] = sample;
        }
      }
      
      // If buffer is full or we've stopped detecting voice and have some data
      if (this.bufferIndex >= this.bufferSize || 
          (!this.voiceDetected && this.bufferIndex > 0)) {
        
        // Create the final buffer with the exact size of collected samples
        const finalBuffer = this.buffer.slice(0, this.bufferIndex);
        
        // Send the packet
        this.port.postMessage({
          type: 'audioPacket',
          buffer: finalBuffer,
          sampleRate: this.sampleRate,
          timestamp: Date.now()
        });
        
        // Reset for next packet
        this.bufferIndex = 0;
      }
    } else if (this.bufferIndex > 0) {
      // If voice detection just ended and we have some data, send what we have
      const finalBuffer = this.buffer.slice(0, this.bufferIndex);
      
      this.port.postMessage({
        type: 'audioPacket',
        buffer: finalBuffer,
        sampleRate: this.sampleRate,
        timestamp: Date.now()
      });
      
      this.bufferIndex = 0;
    }
    
    return true;
  }
}

registerProcessor('audio-processor', AudioProcessor);

// Simple audio processor that just captures audio in fixed chunks
// No voice detection, no filtering, just raw audio
class SimpleAudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // Fixed 500ms buffer at 44.1kHz (mono)
    this.sampleRate = 44100;
    this.bufferDuration = 0.5; // seconds
    this.bufferSize = Math.floor(this.sampleRate * this.bufferDuration);
    this.buffer = new Float32Array(this.bufferSize);
    this.bufferIndex = 0;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (!input || !input.length) return true;
    
    const inputChannel = input[0];
    
    // Simply copy samples to buffer
    for (let i = 0; i < inputChannel.length; i++) {
      this.buffer[this.bufferIndex++] = inputChannel[i];
      
      // When buffer is full, send it and reset
      if (this.bufferIndex >= this.bufferSize) {
        this.port.postMessage({
          buffer: this.buffer.slice(0),
          sampleRate: this.sampleRate
        });
        
        this.bufferIndex = 0;
      }
    }
    
    return true;
  }
}

registerProcessor('simple-audio-processor', SimpleAudioProcessor);