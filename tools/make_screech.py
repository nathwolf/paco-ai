"""Synthesise Paco's screech (original, generated): four loud, high, harsh parrot squawks. Run once; output is committed."""
import numpy as np, wave
from pathlib import Path
from scipy.signal import butter, sosfilt

SR = 44100
rng = np.random.default_rng(7)

def squawk(duration, f_start, f_peak, f_end):
    n = int(SR * duration); t = np.arange(n) / SR
    # Pitch contour: fast rise, then a falling tail, with jitter and a 70 Hz wobble for rasp.
    contour = np.interp(t, [0, duration * .25, duration], [f_start, f_peak, f_end])
    jitter = np.cumsum(rng.normal(0, 1, n)); jitter = (jitter - jitter.mean()) / (np.abs(jitter).max() + 1e-9)
    f0 = contour * (1 + .06 * np.sin(2 * np.pi * 70 * t) + .04 * jitter)
    phase = 2 * np.pi * np.cumsum(f0) / SR
    tone = sum((1 / k ** .5) * np.sin(k * phase + rng.uniform(0, 6.28)) for k in range(1, 6) if k * f_peak < 18000)
    tone *= 1 + .5 * np.sin(2 * np.pi * 115 * t)                      # roughness
    noise = sosfilt(butter(4, [1500, 5500], 'bandpass', fs=SR, output='sos'), rng.normal(0, 1, n))
    x = tone / np.abs(tone).max() + .35 * noise / np.abs(noise).max()
    for low, high in ((2600, 3600), (4200, 5600)):                     # peaks where hearing is most sensitive
        x = x + .8 * sosfilt(butter(2, [low, high], 'bandpass', fs=SR, output='sos'), x)
    env = np.minimum(1, t / .012) * np.minimum(1, (duration - t) / .07) ** 1.5
    return np.tanh(4.5 * x * env)                                      # heavy clipping: loud all the way through

gap = lambda s: np.zeros(int(SR * s))
sound = np.concatenate([squawk(.34, 2300, 3400, 2700), gap(.05), squawk(.24, 2600, 3600, 3000), gap(.05),
                        squawk(.30, 2400, 3500, 2800), gap(.06), squawk(.62, 2200, 3500, 2300)])
sound = sosfilt(butter(2, 900, 'highpass', fs=SR, output='sos'), sound)
sound = .89 * sound / np.abs(sound).max()                                # peak −1 dBFS; short, so loud but not sustained
out = Path(__file__).resolve().parent.parent / 'assets/sounds/paco-screech.wav'
with wave.open(str(out), 'wb') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((sound * 32767).astype('<i2').tobytes())
print(out, round(len(sound) / SR, 2), 's')
