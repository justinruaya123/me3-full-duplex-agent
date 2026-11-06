"""Bounded, request-local Whisper features and automatic language detection."""

import math
from contextlib import contextmanager

_EMPTY = object()


class _RequestEncoder:
    def __init__(self, encode, key):
        self._encode, self._key_for = encode, key
        self._key, self._features = _EMPTY, None
        self._closed = False

    def __call__(self, mel):
        if self._closed:
            raise RuntimeError("Encoder request is closed")
        key = self._key_for(mel)
        if key != self._key:
            features = self._encode(mel)
            self._key, self._features = key, features
        return self._features

    def close(self):
        self._closed = True
        self._key, self._features = _EMPTY, None
        self._encode = self._key_for = None


@contextmanager
def request_encoder(model, *, key):
    """Release request audio and restore the encoder on every exit."""
    original = model.encoder
    if isinstance(original, _RequestEncoder):
        raise RuntimeError("Encoder request is already active")
    encoder = _RequestEncoder(original, key)
    model.encoder = encoder
    try:
        yield
    finally:
        model.encoder = original
        encoder.close()


def _mel_key(mel):
    import numpy as np

    # Snapshot actual values: identity/prefix matching could reuse stale audio.
    values = np.asarray(mel)
    return values.shape, values.dtype.str, values.tobytes()


def _strongest_language(probabilities):
    if not isinstance(probabilities, dict) or not probabilities:
        raise ValueError("Missing automatic language probabilities")
    for language, probability in probabilities.items():
        if (
            not isinstance(language, str) or not language
            or isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not math.isfinite(probability) or not 0 <= probability <= 1
        ):
            raise ValueError("Invalid automatic language probabilities")
    language = max(probabilities, key=probabilities.get)
    return language, probabilities[language]


def automatic_language(probabilities, redetect):
    """Use shared features only for confident automatic language detection.

    Low-confidence interjections retain the installed model's standard
    language-detection input. Confidence is not an ownership or turn gate.
    No language, including English, is assumed when detection fails.
    """
    language, confidence = _strongest_language(probabilities)
    if confidence < 0.95:
        language, _ = _strongest_language(redetect())
    return language


def transcribe_whisper(audio, model_id: str) -> dict:
    """Keep full context, auto language detection and real word timestamps."""
    import importlib

    import mlx.core as mx

    if audio.ndim != 1 or not 0 < len(audio) <= 16 * 16000:
        raise ValueError("Whisper requires <=16s mono audio at 16kHz")
    whisper = importlib.import_module("mlx_whisper.transcribe")
    model = whisper.ModelHolder.get_model(model_id, mx.float16)
    original = model.encoder
    mel = whisper.log_mel_spectrogram(
        audio, n_mels=model.dims.n_mels, padding=whisper.N_SAMPLES
    )
    frames = mel.shape[-2] - whisper.N_FRAMES
    # Match the installed decoder's full 30s input exactly, including its
    # zero padding after all captured audio. No audio or context is cropped.
    decode_mel = whisper.pad_or_trim(
        mel[:frames], whisper.N_FRAMES, axis=-2
    ).astype(mx.float16)

    def standard_language():
        standard_mel = whisper.pad_or_trim(
            mel, whisper.N_FRAMES, axis=-2
        ).astype(mx.float16)
        # Encode separately so the request memo still contains decode_mel.
        # detect_language officially accepts already-encoded audio features.
        features = original(standard_mel[None])
        return model.detect_language(features[0])[1]

    # The speech service owns this model and admits one native ASR call. Decode
    # and alignment can reuse identical features without retaining another
    # request's mel/audio or changing the selected model or its weights.
    with request_encoder(model, key=_mel_key):
        _, probabilities = model.detect_language(decode_mel)
        language = automatic_language(probabilities, standard_language)
        return whisper.transcribe(
            audio, path_or_hf_repo=model_id,
            word_timestamps=True, verbose=None, language=language,
        )
