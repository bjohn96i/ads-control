"""A still picture from a doorbell preview clip (Google sends no event pictures for WebRTC cameras)."""

import io
from fractions import Fraction

import av


def still_frame(mp4: bytes) -> bytes:
    """The middle frame of a short MP4, as a JPEG."""
    try:
        with av.open(io.BytesIO(mp4)) as clip:
            frames = list(clip.decode(video=0))
        frame = frames[len(frames) // 2].reformat(format="yuvj420p")
        encoder = av.CodecContext.create("mjpeg", "w")
        encoder.width, encoder.height = frame.width, frame.height
        encoder.pix_fmt = "yuvj420p"
        encoder.time_base = Fraction(1, 25)
        frame.pts = None
        packets = encoder.encode(frame) + encoder.encode(None)
    except (av.FFmpegError, IndexError) as exc:
        raise ValueError(f"preview clip could not be read: {type(exc).__name__}") from exc
    return b"".join(bytes(p) for p in packets)
