import json
from io import BytesIO
from PIL import Image
import numpy as np
from obed_edom import watercolour
from obed_edom.watercolour import WatercolourOptions, convert, render

def png(color, size=(32,24)):
    out=BytesIO(); Image.new('RGBA',size,color).save(out,'PNG'); return out.getvalue()

def _landmark_png():
    rng=np.random.default_rng(5); width,height=400,300
    pixels=np.clip(np.array([60,90,160],np.float32)+rng.normal(0,12,(height,width,3)),0,255).astype(np.uint8)
    pixels[66:232,110:288]=np.array([230,90,40],np.uint8)
    out=BytesIO(); Image.fromarray(pixels,'RGB').convert('RGBA').save(out,'PNG'); return out.getvalue()

def test_convert_is_deterministic_and_keeps_size():
    raw=png((80,140,210,255)); a,size=convert(raw,WatercolourOptions(seed=7)); b,_=convert(raw,WatercolourOptions(seed=7)); assert a==b and size==(32,24)

def test_transparent_mask_preserves_alpha_without_black_fringe():
    image=Image.open(BytesIO(png((220,80,40,255)))).convert('RGBA')
    mask=Image.new('L',image.size,0)
    for y in range(6,18):
        for x in range(8,24): mask.putpixel((x,y),255)
    result=render(image,WatercolourOptions(transparent=True,seed=2),mask)
    assert result.getpixel((0,0))[3] == 0
    assert result.getpixel((16,12))[3] > 240
    assert result.getpixel((16,12))[0] > 40

def test_studio_batch_request_persists_success_and_per_item_error():
    from obed_edom.web.app import app, RUNNER
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.post('/api/watercolour', files=[('files',('good.png',png((90,140,210,255)),'image/png')),('files',('bad.png',b'not-image','image/png'))])
    assert response.status_code == 200, response.text
    job_id=response.json()['id']
    import time
    for _ in range(80):
        job=client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in {'done','error'}: break
        time.sleep(.03)
    items=job['result']['items']
    assert [item['status'] for item in items] == ['done','error']
    assert client.get(f"/api/watercolour/{job_id}/items/{items[0]['id']}/original").status_code == 200
    assert client.get(f"/api/watercolour/{job_id}/items/{items[0]['id']}/result").status_code == 200

def test_delete_purges_watercolour_output_dir():
    from pathlib import Path
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.post('/api/watercolour', files=[('files',('good.png',png((90,140,210,255)),'image/png'))])
    assert response.status_code == 200, response.text
    job_id=response.json()['id']
    import time
    for _ in range(80):
        job=client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in {'done','error'}: break
        time.sleep(.03)
    output_dir=job['result']['outputDir']
    assert Path(output_dir).is_dir()
    assert client.delete(f'/api/jobs/{job_id}').status_code == 200
    assert not Path(output_dir).exists()
    assert client.get(f'/api/jobs/{job_id}').status_code == 404

def test_white_input_is_reserved_as_bare_paper():
    # Watercolour is subtractive: a white photo has no pigment, so the output must be the cream paper itself.
    raw=png((255,255,255,255),(96,72)); payload,_=convert(raw,WatercolourOptions(seed=3))
    import numpy as np
    out=np.asarray(Image.open(BytesIO(payload)).convert('RGB'),dtype=np.float32)
    assert np.abs(out.mean(axis=(0,1)) - np.array([245,232,201])).max() < 6
    assert out.min() > 175

def test_saturated_highlight_keeps_pigment():
    # A bright but strongly coloured area (sunlit terracotta dome) must not be blown out to bare paper.
    raw=png((235,120,90,255),(96,72)); payload,_=convert(raw,WatercolourOptions(seed=3))
    import numpy as np
    out=np.asarray(Image.open(BytesIO(payload)).convert('RGB'),dtype=np.float32)
    centre=out[24:48,32:64].mean(axis=(0,1))
    assert centre[0] - centre[2] > 40
    assert centre[2] < 190

def test_dark_source_keeps_more_pigment_than_white_with_a_fixed_seed():
    dark, _ = convert(png((28, 30, 34, 255), (96, 72)), WatercolourOptions(seed=17))
    bright, _ = convert(png((245, 245, 245, 255), (96, 72)), WatercolourOptions(seed=17))
    dark_pixels = np.asarray(Image.open(BytesIO(dark)).convert("RGB"), dtype=np.float32)
    bright_pixels = np.asarray(Image.open(BytesIO(bright)).convert("RGB"), dtype=np.float32)
    assert dark_pixels.mean() < bright_pixels.mean() - 35
    repeated, _ = convert(png((28, 30, 34, 255), (96, 72)), WatercolourOptions(seed=17))
    assert repeated == dark


def test_no_wobble_consumes_the_same_random_draws_as_the_previous_helper():
    shape = (31, 47, 3)
    actual = np.random.default_rng(91)
    prior = np.random.default_rng(91)
    watercolour._wobble(np.zeros(shape, np.float32), actual, 1.3)
    watercolour._noise(prior, shape[:2], 9 * 1.3)
    watercolour._noise(prior, shape[:2], 9 * 1.3)
    assert actual.bit_generator.state == prior.bit_generator.state


def test_preview_renders_the_bundled_sample():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.get('/api/watercolour/preview', params={'wash_softness':0.2,'ink_amount':0.9})
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'image/png'
    image=Image.open(BytesIO(response.content))
    assert max(image.size) <= 360
    response=client.get('/api/watercolour/preview', params={'wash_softness':1.4,'ink_amount':0.5})
    assert response.status_code == 400


def test_preview_uses_an_uploaded_photo():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.post(
        '/api/watercolour/preview',
        files={'file':('shot.png',png((90,140,210,255),(720,540)),'image/png')},
        data={'wash_softness':'0.65','ink_amount':'0.42'},
    )
    assert response.status_code == 200, response.text
    image=Image.open(BytesIO(response.content))
    assert image.size == (360, 270)


def test_preview_cuts_out_the_landmark_rect():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.post(
        '/api/watercolour/preview',
        files={'file':('landmark.png',_landmark_png(),'image/png')},
        data={'mask':json.dumps({'transparent':True,'rect':[110,66,178,166]})},
    )
    assert response.status_code == 200, response.text
    image=Image.open(BytesIO(response.content))
    assert image.mode == 'RGBA'
    assert max(image.size) <= 360
    alpha=np.asarray(image)[:,:,3]
    assert (alpha == 0).any() and (alpha == 255).any()


def _mask_png(box, size=(400, 300)):
    mask = Image.new('L', size, 0)
    x0, y0, x1, y1 = box
    for y in range(y0, y1):
        for x in range(x0, x1):
            mask.putpixel((x, y), 255)
    out = BytesIO(); mask.save(out, 'PNG'); import base64; return base64.b64encode(out.getvalue()).decode('ascii')


def test_preview_keep_mask_forces_opaque_centre():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    response = client.post(
        '/api/watercolour/preview',
        files={'file': ('landmark.png', _landmark_png(), 'image/png')},
        data={'mask': json.dumps({
            'transparent': True,
            'rect': [110, 66, 178, 166],
            'keepMask': _mask_png((180, 130, 220, 170)),
            'maskSize': [400, 300],
        })},
    )
    assert response.status_code == 200, response.text
    image = Image.open(BytesIO(response.content)).convert('RGBA')
    factor = image.width / 400
    cx, cy = round(200 * factor), round(150 * factor)
    assert image.getpixel((cx, cy))[3] == 255


def test_preview_remove_mask_clears_pixels():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    response = client.post(
        '/api/watercolour/preview',
        files={'file': ('landmark.png', _landmark_png(), 'image/png')},
        data={'mask': json.dumps({
            'transparent': True,
            'rect': [110, 66, 178, 166],
            'removeMask': _mask_png((130, 90, 260, 200)),
            'maskSize': [400, 300],
        })},
    )
    assert response.status_code == 200, response.text
    image = Image.open(BytesIO(response.content)).convert('RGBA')
    factor = image.width / 400
    cx, cy = round(200 * factor), round(150 * factor)
    assert image.getpixel((cx, cy))[3] == 0


def test_preview_rejects_malformed_mask_png():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    response = client.post(
        '/api/watercolour/preview',
        files={'file': ('landmark.png', _landmark_png(), 'image/png')},
        data={'mask': json.dumps({
            'transparent': True,
            'rect': [110, 66, 178, 166],
            'keepMask': 'not-base64!!',
        })},
    )
    assert response.status_code == 400
    assert 'invalid' in response.text.lower()


def test_preview_rejects_transparent_without_a_rect():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.post(
        '/api/watercolour/preview',
        files={'file':('landmark.png',_landmark_png(),'image/png')},
        data={'mask':json.dumps({'transparent':True})},
    )
    assert response.status_code == 400
    assert 'foreground rectangle' in response.text.lower()


def test_slider_gains_are_exactly_neutral_at_the_defaults():
    assert watercolour._slider_gain(0.42, 0.42, 0.60, 0.435) == 1.0
    assert watercolour._slider_gain(0.65, 0.65, -0.30, -0.85) == 1.0
    assert watercolour._slider_gain(0.0, 0.42, 0.60, 0.435) < 0.5 and watercolour._slider_gain(1.0, 0.42, 0.60, 0.435) > 1.5

def _sample():
    from obed_edom.web.watercolour import SAMPLE_PATH
    return Image.open(BytesIO(SAMPLE_PATH.read_bytes()))

def test_ink_amount_zero_removes_pencil_marks():
    lo=np.asarray(render(_sample(), WatercolourOptions(ink_amount=0.0)),dtype=np.float32)
    hi=np.asarray(render(_sample(), WatercolourOptions(ink_amount=1.0)),dtype=np.float32)
    assert np.abs(lo-hi).mean() > 11
    assert (lo.mean(axis=2) < 110).sum() < (hi.mean(axis=2) < 110).sum()

def test_wash_softness_extremes_change_luminance():
    crisp=np.asarray(render(_sample(), WatercolourOptions(wash_softness=0.0)),dtype=np.float32)
    airy=np.asarray(render(_sample(), WatercolourOptions(wash_softness=1.0)),dtype=np.float32)
    assert np.abs(crisp-airy).mean() > 28 and airy.mean() > crisp.mean() + 20

