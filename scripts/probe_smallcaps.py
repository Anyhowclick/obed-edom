"""Scratch probe: measure ink heights of "Lord" on rendered previews."""

from __future__ import annotations

import sys

import numpy as np
import Quartz
import Vision
from Foundation import NSURL, NSRange
from PIL import Image


def word_boxes(path: str, word: str = "Lord"):
    url = NSURL.fileURLWithPath_(path)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(False)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
    handler.performRequests_error_([req], None)
    out = []
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)[0]
        text = str(cand.string())
        start = 0
        while True:
            i = text.find(word, start)
            if i < 0:
                break
            box, _ = cand.boundingBoxForRange_error_(NSRange(i, len(word)), None)
            if box:
                bb = box.boundingBox()
                out.append(
                    (bb.origin.x, bb.origin.y, bb.size.width, bb.size.height, text[max(0, i - 10) : i + 14])
                )
            start = i + 1
    return out


def profile(path: str, box) -> tuple | None:
    im = Image.open(path).convert("L")
    W, H = im.size
    x, y, w, h, ctx = box
    px0, px1 = int(x * W), int((x + w) * W)
    py0, py1 = int((1 - y - h) * H), int((1 - y) * H)
    crop = im.crop((px0, py0, px1, py1))
    a = np.asarray(crop).astype(float)
    if a.size == 0:
        return None
    bg = np.median(a)
    ink = np.abs(a - bg) > 60
    if not ink.any():
        return None
    tops = np.full(ink.shape[1], 10**6)
    for c in range(ink.shape[1]):
        col = np.where(ink[:, c])[0]
        if len(col):
            tops[c] = col[0]
    idx = np.where(tops < 10**6)[0]
    if len(idx) < 4:
        return None
    gaps = np.where(np.diff(idx) > 2)[0]
    lend = idx[gaps[0]] if len(gaps) else idx[len(idx) // 4]
    left = idx[idx <= lend]
    rest = idx[idx > lend]
    if len(rest) == 0:
        return None
    ltop, rtop = tops[left].min(), tops[rest].min()
    height = ink.shape[0]
    return round(float(ltop), 1), round(float(rtop), 1), height, round((rtop - ltop) / height, 3), ctx


if __name__ == "__main__":
    for path in sys.argv[1:]:
        print("==", path)
        for box in word_boxes(path):
            print("  ", profile(path, box))
