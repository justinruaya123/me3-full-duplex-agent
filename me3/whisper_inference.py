"""Exact encoder reuse inside one serialized native Whisper request."""

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
    """Release audio/features and restore the model after success or failure."""
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


def transcribe_whisper(audio, model_id: str) -> dict:
    """Keep full context, auto language detection and real word timestamps."""
    import importlib

    import mlx.core as mx

    whisper = importlib.import_module("mlx_whisper.transcribe")
    model = whisper.ModelHolder.get_model(model_id, mx.float16)
    # The speech service owns this model and admits one native ASR call. Decode
    # and alignment can reuse identical features without retaining another
    # request's mel/audio or changing the selected model or its weights.
    with request_encoder(model, key=_mel_key):
        return whisper.transcribe(
            audio, path_or_hf_repo=model_id,
            word_timestamps=True, verbose=None,
        )
