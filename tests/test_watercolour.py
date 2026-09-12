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


def _landmark_with_intruder_png():
    rng=np.random.default_rng(5); width,height=400,300
    pixels=np.clip(np.array([60,90,160],np.float32)+rng.normal(0,12,(height,width,3)),0,255).astype(np.uint8)
    pixels[66:232,110:288]=np.array([230,90,40],np.uint8)
    pixels[80:140,240:300]=np.array([180,60,60],np.uint8)
    out=BytesIO(); Image.fromarray(pixels,'RGB').convert('RGBA').save(out,'PNG'); return out.getvalue()


def _painted_keep_mask(size=(400,300)):
    mask=Image.new('L',size,0)
    for y in range(66,232):
        for x in range(110,288):
            if not (80<=y<140 and 240<=x<300):
                mask.putpixel((x,y),255)
    return mask


def test_painted_keep_mask_is_authoritative_over_the_intruder():
    from obed_edom import watercolour
    image=Image.open(BytesIO(_landmark_with_intruder_png())).convert('RGBA')
    rect=(110.0,66.0,178.0,166.0)
    alpha=np.asarray(watercolour.grabcut_mask(image,rect,keep_mask=_painted_keep_mask()))
    assert alpha[149,199] == 255
    assert alpha[110,270] == 0
    assert alpha[10,10] == 0


def test_painted_keep_mask_control_without_painting_keeps_the_intruder():
    from obed_edom import watercolour
    image=Image.open(BytesIO(_landmark_with_intruder_png())).convert('RGBA')
    rect=(110.0,66.0,178.0,166.0)
    alpha=np.asarray(watercolour.grabcut_mask(image,rect,keep_mask=None))
    assert alpha[110,270] > 0


def test_painted_remove_mask_beats_keep_on_overlap():
    from obed_edom import watercolour
    image=Image.open(BytesIO(_landmark_png())).convert('RGBA')
    size=image.size
    keep=Image.new('L',size,0)
    for y in range(80,180):
        for x in range(150,250): keep.putpixel((x,y),255)
    remove=Image.new('L',size,0)
    for y in range(80,180):
        for x in range(150,250): remove.putpixel((x,y),255)
    alpha=np.asarray(watercolour.grabcut_mask(image,(110.0,66.0,178.0,166.0),keep_mask=keep,remove_mask=remove))
    assert alpha[130,200] == 0


def test_all_black_keep_mask_with_rect_matches_keep_mask_none():
    from obed_edom import watercolour
    image=Image.open(BytesIO(_landmark_png())).convert('RGBA')
    rect=(110.0,66.0,178.0,166.0)
    black_keep=Image.new('L',image.size,0)
    with_black=watercolour.grabcut_mask(image,rect,keep_mask=black_keep)
    without=watercolour.grabcut_mask(image,rect,keep_mask=None)
    assert with_black.tobytes() == without.tobytes()


def test_max_value_127_keep_mask_matches_keep_mask_none():
    from obed_edom import watercolour
    image=Image.open(BytesIO(_landmark_png())).convert('RGBA')
    rect=(110.0,66.0,178.0,166.0)
    grey_keep=Image.new('L',image.size,127)
    with_grey=watercolour.grabcut_mask(image,rect,keep_mask=grey_keep)
    without=watercolour.grabcut_mask(image,rect,keep_mask=None)
    assert with_grey.tobytes() == without.tobytes()


def test_unpainted_keep_mask_matches_none_on_a_textured_adversarial_image():
    from obed_edom import watercolour
    rng=np.random.default_rng(11)
    width,height=200,150
    pixels=(rng.random((height,width,3))*255).astype(np.uint8)
    image=Image.fromarray(pixels,'RGB').convert('RGBA')
    rect=(20.0,20.0,150.0,110.0)
    unpainted_keep=Image.new('L',image.size,100)
    with_keep=watercolour.grabcut_mask(image,rect,keep_mask=unpainted_keep)
    without=watercolour.grabcut_mask(image,rect,keep_mask=None)
    assert with_keep.tobytes() == without.tobytes()


def test_upscaled_painted_keep_mask_gives_a_soft_transition_edge():
    from obed_edom import watercolour
    image=Image.new('RGBA',(640,480),(200,120,60,255))
    small=Image.new('L',(64,48),0)
    for y in range(0,24):
        for x in range(0,32): small.putpixel((x,y),255)
    alpha=np.asarray(watercolour.grabcut_mask(image,None,keep_mask=small))
    row=alpha[120,:].astype(np.int32)
    mid=np.flatnonzero((row>0)&(row<255))
    assert mid.size > 0
    band=mid.max()-mid.min()+1
    assert 4 <= band <= 24


def test_preview_endpoint_agrees_with_direct_mask_for_on_the_full_image():
    from obed_edom.web.app import app
    from obed_edom.web import watercolour as web_watercolour
    from fastapi.testclient import TestClient
    from PIL import Image as PILImage
    client=TestClient(app)
    raw=_landmark_with_intruder_png()
    keep_mask_b64=base64_of(_painted_keep_mask())
    spec={'transparent':True,'keepMask':keep_mask_b64,'maskSize':[400,300]}
    response=client.post(
        '/api/watercolour/preview',
        files={'file':('landmark.png',raw,'image/png')},
        data={'mask':json.dumps(spec)},
    )
    assert response.status_code == 200, response.text
    preview_alpha=np.asarray(PILImage.open(BytesIO(response.content)).convert('RGBA'))[:,:,3]
    full_image=Image.open(BytesIO(raw)).convert('RGBA')
    full_mask=web_watercolour._mask_for(full_image, spec)
    full_payload,_=watercolour.convert(raw, WatercolourOptions(transparent=True,paper=False), full_mask)
    full_alpha=np.asarray(PILImage.open(BytesIO(full_payload)).convert('RGBA'))[:,:,3]
    factor=preview_alpha.shape[1]/full_alpha.shape[1]
    resized=np.asarray(Image.fromarray(full_alpha).resize((preview_alpha.shape[1],preview_alpha.shape[0]),Image.LANCZOS)).astype(np.float32)
    preview_f=preview_alpha.astype(np.float32)
    edge=((preview_f>5)&(preview_f<250))|((resized>5)&(resized<250))
    assert edge.any()
    assert np.abs(resized[edge]-preview_f[edge]).mean() < 40
    intruder_x,intruder_y=round(270*factor),round(110*factor)
    assert preview_alpha[intruder_y,intruder_x] == 0
    assert full_alpha[110,270] == 0


def _rgba_with_transparent_border(size=(400,300)):
    width,height=size
    rng=np.random.default_rng(5)
    pixels=np.clip(np.array([60,90,160],np.float32)+rng.normal(0,12,(height,width,3)),0,255).astype(np.uint8)
    pixels[66:232,110:288]=np.array([230,90,40],np.uint8)
    image=Image.fromarray(pixels,'RGB').convert('RGBA')
    alpha=np.full((height,width),255,np.uint8)
    alpha[:20,:]=0
    arr=np.asarray(image).copy(); arr[:,:,3]=alpha
    return Image.fromarray(arr,'RGBA')


def test_mask_for_honours_painted_keep_mask_on_rgba_with_transparency_and_no_rect():
    from obed_edom.web import watercolour as web_watercolour
    image=_rgba_with_transparent_border()
    keep=Image.new('L',image.size,0)
    for y in range(180,220):
        for x in range(50,90): keep.putpixel((x,y),255)
    out=BytesIO(); keep.save(out,'PNG'); import base64
    spec={'transparent':True,'keepMask':base64.b64encode(out.getvalue()).decode('ascii'),'maskSize':list(image.size)}
    mask=web_watercolour._mask_for(image,spec)
    alpha=np.asarray(mask.convert('L'))
    assert alpha[200,70] == 255
    assert alpha[0,0] == 0


def test_grabcut_mask_rejects_non_positive_rect_on_painted_path():
    from obed_edom import watercolour
    image=Image.open(BytesIO(_landmark_png())).convert('RGBA')
    keep=_painted_keep_mask()
    import pytest
    with pytest.raises(watercolour.WatercolourError):
        watercolour.grabcut_mask(image,(110.0,66.0,0.0,166.0),keep_mask=keep)


def test_grabcut_mask_rejects_out_of_bounds_point_on_painted_path():
    from obed_edom import watercolour
    image=Image.open(BytesIO(_landmark_png())).convert('RGBA')
    keep=_painted_keep_mask()
    import pytest
    with pytest.raises(watercolour.WatercolourError):
        watercolour.grabcut_mask(image,None,foreground=[(1000.0,1000.0)],keep_mask=keep)


def test_grabcut_mask_rejects_too_many_points_on_painted_path():
    from obed_edom import watercolour
    image=Image.open(BytesIO(_landmark_png())).convert('RGBA')
    keep=_painted_keep_mask()
    import pytest
    with pytest.raises(watercolour.WatercolourError):
        watercolour.grabcut_mask(image,None,foreground=[(1.0,1.0)]*501,keep_mask=keep)


def test_preview_rejects_non_positive_rect_dimensions():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.post(
        '/api/watercolour/preview',
        files={'file':('landmark.png',_landmark_png(),'image/png')},
        data={'mask':json.dumps({'transparent':True,'rect':[110,66,0,166]})},
    )
    assert response.status_code == 400


def test_preview_rejects_out_of_bounds_foreground_point_on_painted_path():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.post(
        '/api/watercolour/preview',
        files={'file':('landmark.png',_landmark_png(),'image/png')},
        data={'mask':json.dumps({
            'transparent':True,
            'keepMask':base64_of(_painted_keep_mask()),
            'maskSize':[400,300],
            'foreground':[[10000,10000]],
        })},
    )
    assert response.status_code == 400


def test_preview_rejects_too_many_points_on_painted_path():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.post(
        '/api/watercolour/preview',
        files={'file':('landmark.png',_landmark_png(),'image/png')},
        data={'mask':json.dumps({
            'transparent':True,
            'keepMask':base64_of(_painted_keep_mask()),
            'maskSize':[400,300],
            'foreground':[[1,1]]*501,
        })},
    )
    assert response.status_code == 400


def test_preview_post_with_keep_mask_and_no_rect_succeeds():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.post(
        '/api/watercolour/preview',
        files={'file':('landmark.png',_landmark_png(),'image/png')},
        data={'mask':json.dumps({'transparent':True,'keepMask':base64_of(_painted_keep_mask()),'maskSize':[400,300]})},
    )
    assert response.status_code == 200, response.text
    alpha=np.asarray(Image.open(BytesIO(response.content)).convert('RGBA'))[:,:,3]
    assert (alpha == 0).any() and (alpha == 255).any()


def base64_of(mask):
    out=BytesIO(); mask.save(out,'PNG'); import base64; return base64.b64encode(out.getvalue()).decode('ascii')


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


def test_fill_hidden_decontaminates_soft_alpha_fringe_against_a_contrasting_background():
    from obed_edom import watercolour
    size=64
    object_colour=np.array([20,200,20],np.float32)
    background_colour=np.array([220,20,220],np.float32)
    rgb=np.broadcast_to(background_colour,(size,size,3)).copy()
    rgb[16:48,16:48]=object_colour
    alpha=np.zeros((size,size),np.float32)
    alpha[16:48,16:48]=255
    yy,xx=np.mgrid[0:size,0:size]
    ring=(np.maximum(np.abs(yy-31.5),np.abs(xx-31.5))>15)&(np.maximum(np.abs(yy-31.5),np.abs(xx-31.5))<=17)
    alpha[ring]=128
    rgb[ring]=(object_colour+background_colour)/2
    filled=watercolour._fill_hidden(rgb.astype(np.uint8),alpha.astype(np.uint8),scale=1.0)
    fringe=filled[ring].astype(np.float32)
    dist_object=np.abs(fringe-object_colour).mean()
    dist_background=np.abs(fringe-background_colour).mean()
    assert dist_object < 60
    assert dist_object < dist_background


def test_transparent_hard_edge_stays_crisp():
    image=Image.new('RGBA',(64,64),(220,80,40,0))
    for y in range(20,44):
        for x in range(20,44): image.putpixel((x,y),(220,80,40,255))
    result=render(image,WatercolourOptions(transparent=True,seed=2))
    assert result.getpixel((10,10))[3] == 0
    assert result.getpixel((32,32))[3] == 255


def _rect_mask_spec(rect=(10,10,20,20)):
    return {'transparent': True, 'rect': list(rect)}


def test_preview_rejects_non_dict_masks_at_top_level():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.post(
        '/api/watercolour/preview',
        files={'file':('landmark.png',_landmark_png(),'image/png')},
        data={'mask':json.dumps([1,2,3])},
    )
    assert response.status_code == 400


def test_preview_rejects_rect_with_wrong_length():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.post(
        '/api/watercolour/preview',
        files={'file':('landmark.png',_landmark_png(),'image/png')},
        data={'mask':json.dumps({'transparent':True,'rect':[10,10,20]})},
    )
    assert response.status_code == 400
    assert 'invalid' in response.text.lower()


def test_preview_rejects_non_finite_rect():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.post(
        '/api/watercolour/preview',
        files={'file':('landmark.png',_landmark_png(),'image/png')},
        data={'mask':'{"transparent": true, "rect": [380, 280, NaN, Infinity]}'},
    )
    assert response.status_code == 400


def test_preview_rejects_rect_outside_image():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.post(
        '/api/watercolour/preview',
        files={'file':('landmark.png',_landmark_png(),'image/png')},
        data={'mask':json.dumps({'transparent':True,'rect':[380,280,100,100]})},
    )
    assert response.status_code == 400


def test_preview_rejects_malformed_foreground_points():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.post(
        '/api/watercolour/preview',
        files={'file':('landmark.png',_landmark_png(),'image/png')},
        data={'mask':json.dumps({'transparent':True,'rect':[110,66,178,166],'foreground':[[1,2,3]]})},
    )
    assert response.status_code == 400
    response=client.post(
        '/api/watercolour/preview',
        files={'file':('landmark.png',_landmark_png(),'image/png')},
        data={'mask':json.dumps({'transparent':True,'rect':[110,66,178,166],'foreground':[['a','b']]})},
    )
    assert response.status_code == 400


def test_start_watercolour_rejects_malformed_masks_field():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    response=client.post('/api/watercolour', files=[('files',('good.png',png((90,140,210,255)),'image/png'))], data={'masks':'[]'})
    assert response.status_code == 400
    response=client.post('/api/watercolour', files=[('files',('good.png',png((90,140,210,255)),'image/png'))], data={'masks':'{"0": 5}'})
    assert response.status_code == 400


def test_batch_out_of_bounds_mask_rejected_at_submit_not_500():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    masks=json.dumps({'0': _rect_mask_spec((380,280,100,100))})
    response=client.post('/api/watercolour', files=[('files',('good.png',_landmark_png(),'image/png'))], data={'masks':masks})
    assert response.status_code == 400, response.text
    assert 'good.png' in response.json()['detail']


def test_batch_duplicate_filenames_processed_independently():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    masks=json.dumps({'1': _rect_mask_spec((110,66,178,166))})
    response=client.post(
        '/api/watercolour',
        files=[('files',('good.png',_landmark_png(),'image/png')),('files',('good.png',_landmark_png(),'image/png'))],
        data={'masks':masks},
    )
    assert response.status_code == 200, response.text
    job_id=response.json()['id']
    import time
    for _ in range(80):
        job=client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in {'done','error'}: break
        time.sleep(.03)
    items=job['result']['items']
    assert [item['status'] for item in items] == ['done','done']
    assert items[0]['transparent'] is False
    assert items[1]['transparent'] is True
    assert items[0]['result'] != items[1]['result']
    assert client.get(f"/api/watercolour/{job_id}/items/{items[0]['id']}/result").status_code == 200
    assert client.get(f"/api/watercolour/{job_id}/items/{items[1]['id']}/result").status_code == 200


def test_submit_failure_cleans_up_staged_uploads():
    from pathlib import Path
    from obed_edom.paths import output_root
    from obed_edom.web import app as app_module
    from obed_edom.web import watercolour as watercolour_web
    from fastapi.testclient import TestClient
    uploads_dir = output_root() / '.watercolour' / '.uploads'
    before = set(uploads_dir.glob('*')) if uploads_dir.is_dir() else set()

    class _BoomRunner:
        def submit(self, *args, **kwargs):
            raise RuntimeError('boom')

    original = watercolour_web._runner
    watercolour_web._runner = lambda: _BoomRunner()
    try:
        client=TestClient(app_module.app, raise_server_exceptions=False)
        response=client.post('/api/watercolour', files=[('files',('good.png',png((90,140,210,255)),'image/png'))])
    finally:
        watercolour_web._runner = original
    assert response.status_code == 500
    after = set(uploads_dir.glob('*')) if uploads_dir.is_dir() else set()
    assert after == before


def test_batch_rollback_removes_orphan_original_and_tmp_files():
    from pathlib import Path
    from obed_edom.web.app import app
    from obed_edom.web import watercolour as watercolour_web
    from fastapi.testclient import TestClient
    client=TestClient(app)
    original_convert = watercolour_web.convert
    calls = {'n': 0}

    def _flaky_convert(*args, **kwargs):
        calls['n'] += 1
        if calls['n'] == 2:
            raise ValueError('boom')
        return original_convert(*args, **kwargs)

    watercolour_web.convert = _flaky_convert
    try:
        response=client.post(
            '/api/watercolour',
            files=[('files',('a.png',png((90,140,210,255)),'image/png')),('files',('b.png',png((10,20,30,255)),'image/png'))],
        )
        assert response.status_code == 200, response.text
        job_id=response.json()['id']
        import time
        for _ in range(80):
            job=client.get(f'/api/jobs/{job_id}').json()
            if job['status'] in {'done','error'}: break
            time.sleep(.03)
    finally:
        watercolour_web.convert = original_convert
    items=job['result']['items']
    assert [item['status'] for item in items] == ['done','error']
    originals_dir = Path(job['result']['originalDir'])
    assert len(list(originals_dir.glob('*'))) == 1
    output_dir = Path(job['result']['outputDir'])
    assert not list(output_dir.rglob('*.tmp'))


def test_patch_rejects_watercolour_jobs():
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
    response=client.patch(f'/api/jobs/{job_id}', json={'result': {'resultDir': '/etc'}})
    assert response.status_code == 400


def test_result_file_rejects_paths_outside_job_root():
    from obed_edom.web.app import RUNNER
    from obed_edom.web.watercolour import _result_file
    job = RUNNER.submit('watercolour', lambda job: {}, feature='watercolour')
    job.status = 'done'
    job.result = {
        'resultDir': '/etc',
        'originalDir': '/etc',
        'items': [{'id': 'item-1', 'result': 'passwd', 'original': 'passwd'}],
    }
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as excinfo:
        _result_file(job.id, 'item-1', 'result')
    assert excinfo.value.status_code == 404


def test_submit_seeds_result_before_worker_runs():
    import threading
    from obed_edom.web.app import RUNNER
    barrier = threading.Event()

    def _blocked(job):
        barrier.wait(2)
        return {'items': []}

    job = RUNNER.submit('watercolour', _blocked, feature='watercolour', result={'stagingDir': '/tmp/staged'})
    try:
        assert job.result == {'stagingDir': '/tmp/staged'}
    finally:
        barrier.set()


def test_mask_field_rejects_oversized_dimensions_before_decompression():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    huge = Image.new('L', (5000, 5000), 255)
    out = BytesIO(); huge.save(out, 'PNG'); import base64
    encoded = base64.b64encode(out.getvalue()).decode('ascii')
    assert len(out.getvalue()) < 1024 * 1024
    response=client.post(
        '/api/watercolour/preview',
        files={'file':('landmark.png',_landmark_png(),'image/png')},
        data={'mask':json.dumps({'transparent':True,'rect':[110,66,178,166],'keepMask':encoded})},
    )
    assert response.status_code == 400
    assert 'invalid' in response.text.lower()



def test_batch_writes_masks_sidecar_with_spec_and_job_scalars():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    import time
    client=TestClient(app)
    masks=json.dumps({'0': _rect_mask_spec((110,66,178,166))})
    response=client.post(
        '/api/watercolour',
        files=[('files',('landmark.png',_landmark_png(),'image/png'))],
        data={'masks':masks,'wash_softness':'0.7','ink_amount':'0.3'},
    )
    assert response.status_code == 200, response.text
    job_id=response.json()['id']
    for _ in range(80):
        job=client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in {'done','error'}: break
        time.sleep(.03)
    assert job['result']['washSoftness'] == 0.7
    assert job['result']['inkAmount'] == 0.3
    item_id=job['result']['items'][0]['id']
    spec_response=client.get(f'/api/watercolour/{job_id}/items/{item_id}/spec')
    assert spec_response.status_code == 200
    spec=spec_response.json()['spec']
    assert spec['transparent'] is True
    assert spec['rect'] == [110,66,178,166]


def test_spec_route_returns_null_when_masks_sidecar_is_missing():
    from pathlib import Path
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    import time
    client=TestClient(app)
    response=client.post('/api/watercolour', files=[('files',('good.png',png((90,140,210,255)),'image/png'))])
    assert response.status_code == 200, response.text
    job_id=response.json()['id']
    for _ in range(80):
        job=client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in {'done','error'}: break
        time.sleep(.03)
    item_id=job['result']['items'][0]['id']
    sidecar=Path(job['result']['outputDir']) / 'masks.json'
    sidecar.unlink()
    spec_response=client.get(f'/api/watercolour/{job_id}/items/{item_id}/spec')
    assert spec_response.status_code == 200
    assert spec_response.json() == {'spec': None}


def test_spec_route_404s_for_unknown_job_or_item():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    assert client.get('/api/watercolour/nope/items/nope/spec').status_code == 404


def test_default_landmark_size_boundaries():
    from obed_edom.web.watercolour import _default_landmark_size
    assert _default_landmark_size(10) == 240
    assert _default_landmark_size(900) == 900
    assert _default_landmark_size(5000) == 1280
    assert _default_landmark_size(3000) == 1280


def test_grabcut_mask_cancels_between_iterations():
    import time
    import pytest
    image=Image.open(BytesIO(_landmark_png())).convert('RGBA')
    calls={'n':0}
    def cancel():
        calls['n']+=1
        return calls['n']>=2
    start=time.time()
    with pytest.raises(watercolour.WatercolourCancelled):
        watercolour.grabcut_mask(image,(110.0,66.0,178.0,166.0),cancel=cancel)
    assert time.time()-start<1.0
    assert calls['n']==2


def test_render_stops_at_a_stage_boundary():
    import pytest
    image=Image.open(BytesIO(_landmark_png())).convert('RGBA')
    calls={'n':0}
    def cancel():
        calls['n']+=1
        return calls['n']>=3
    with pytest.raises(watercolour.WatercolourCancelled):
        render(image,WatercolourOptions(),cancel=cancel)
    assert calls['n']==3


def test_non_index_mask_key_rejected_at_submit():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    masks=json.dumps({'landmark.png':_rect_mask_spec()})
    response=client.post('/api/watercolour', files=[('files',('landmark.png',_landmark_png(),'image/png'))], data={'masks':masks})
    assert response.status_code == 400, response.text


def test_out_of_bounds_mask_leaves_no_staged_upload_dir():
    from pathlib import Path
    from obed_edom.paths import output_root
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    uploads_dir = output_root() / '.watercolour' / '.uploads'
    before = set(uploads_dir.glob('*')) if uploads_dir.is_dir() else set()
    masks=json.dumps({'0':_rect_mask_spec((380,280,100,100))})
    response=client.post('/api/watercolour', files=[('files',('good.png',_landmark_png(),'image/png'))], data={'masks':masks})
    assert response.status_code == 400
    after = set(uploads_dir.glob('*')) if uploads_dir.is_dir() else set()
    assert after == before


def test_cancel_mid_batch_keeps_finished_discards_inflight_and_marks_remaining_cancelled():
    import threading, time
    from pathlib import Path
    from obed_edom.web.app import app
    from obed_edom.web import watercolour as web_watercolour
    from fastapi.testclient import TestClient
    client=TestClient(app)
    real_convert=web_watercolour.convert
    started=threading.Event()
    calls={'n':0}
    def fake_convert(raw, options, mask=None, *, cancel=None):
        calls['n']+=1
        if calls['n']==2:
            started.set()
            deadline=time.time()+5
            while time.time()<deadline and not (cancel and cancel()):
                time.sleep(0.01)
        return real_convert(raw, options, mask, cancel=cancel)
    web_watercolour.convert=fake_convert
    try:
        files=[('files',(f'{i}.png',png((80+i,90,100,255)),'image/png')) for i in range(3)]
        response=client.post('/api/watercolour', files=files)
        assert response.status_code == 200, response.text
        job_id=response.json()['id']
        assert started.wait(5)
        cancel_response=client.post(f'/api/watercolour/{job_id}/cancel')
        assert cancel_response.status_code == 200
        job=None
        for _ in range(200):
            job=client.get(f'/api/jobs/{job_id}').json()
            if job['status'] in {'done','error'}: break
            time.sleep(0.03)
        assert job['status'] == 'error'
        assert job['error'] == 'Export cancelled.'
        items=job['result']['items']
        assert items[0]['status'] == 'done'
        assert items[1]['status'] == 'cancelled'
        assert items[2]['status'] == 'cancelled'
        assert job['result']['partial'] is True
        assert job['result']['cancelled'] is True
        result_dir=Path(job['result']['resultDir'])
        assert not list(result_dir.glob('01-*'))
        assert (result_dir / items[0]['result']).is_file()
    finally:
        web_watercolour.convert=real_convert


def test_cancelling_a_queued_job_still_cleans_staging():
    import threading, time
    from pathlib import Path
    from obed_edom.web.app import app, RUNNER
    from fastapi.testclient import TestClient
    client=TestClient(app)
    release=threading.Event()
    blocker=RUNNER.submit('watercolour', lambda job: (release.wait(5), {})[1], feature='watercolour')
    try:
        response=client.post('/api/watercolour', files=[('files',('good.png',png((90,140,210,255)),'image/png'))])
        assert response.status_code == 200, response.text
        job_id=response.json()['id']
        job=None
        for _ in range(100):
            job=RUNNER.get(job_id)
            if job.status == 'queued': break
            time.sleep(0.01)
        assert job.status == 'queued'
        staging_dir=Path(job.result['stagingDir'])
        assert staging_dir.is_dir()
        cancel_response=client.post(f'/api/watercolour/{job_id}/cancel')
        assert cancel_response.status_code == 200
        payload=cancel_response.json()
        assert payload['status'] == 'error'
        assert not staging_dir.exists()
        assert payload['result']['cancelled'] is True
        assert payload['result']['partial'] is False
        assert 'stagingDir' not in payload['result']

        saved=json.loads(RUNNER._session_file(job_id).read_text())
        assert saved['result']['cancelled'] is True
        assert 'stagingDir' not in saved['result']
    finally:
        release.set()
        for _ in range(200):
            if RUNNER.get(blocker.id).status in {'done','error'}: break
            time.sleep(0.01)


def test_grabcut_split_iterations_match_monolithic_reference():
    # keep_mask paint takes the _painted_alpha shortcut (no GrabCut at all), so the
    # mask-correction pass is only reachable through remove_mask/foreground/background;
    # this exercises both split points: 5 vs 1+4xGC_EVAL, then 3 vs 1+2xGC_EVAL.
    import cv2
    image=Image.open(BytesIO(_landmark_with_intruder_png())).convert('RGBA')
    rect=(110.0,66.0,178.0,166.0)
    remove=Image.new('L',image.size,0)
    for y in range(110,140):
        for x in range(240,300): remove.putpixel((x,y),255)
    rgb=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2BGR)
    x,y,w,h=round(rect[0]),round(rect[1]),round(rect[2]),round(rect[3])

    mono_mask=np.zeros((image.height,image.width),np.uint8)
    mono_bg=np.zeros((1,65),np.float64)
    mono_fg=np.zeros((1,65),np.float64)
    # GMM initialisation draws from OpenCV's global RNG, so pin it before each
    # pipeline to make the split-vs-monolithic comparison order-independent.
    cv2.setRNGSeed(0)
    cv2.grabCut(rgb,mono_mask,(x,y,w,h),mono_bg,mono_fg,5,cv2.GC_INIT_WITH_RECT)
    resized=remove.resize(image.size,Image.NEAREST)
    flag=np.asarray(resized.convert('L'))>127
    mono_mask[flag]=cv2.GC_BGD
    cv2.grabCut(rgb,mono_mask,None,mono_bg,mono_fg,3,cv2.GC_INIT_WITH_MASK)
    mono_alpha=np.where((mono_mask==cv2.GC_FGD)|(mono_mask==cv2.GC_PR_FGD),255,0).astype(np.uint8)

    cv2.setRNGSeed(0)
    split_alpha=np.asarray(watercolour.grabcut_mask(image,rect,remove_mask=remove))
    assert np.array_equal(split_alpha,mono_alpha)


def test_unicode_digit_and_zero_padded_mask_keys_rejected_at_submit():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    for bad_key in ('00', '٠'):
        masks=json.dumps({bad_key: _rect_mask_spec()})
        response=client.post('/api/watercolour', files=[('files',('good.png',_landmark_png(),'image/png'))], data={'masks':masks})
        assert response.status_code == 400, (bad_key, response.text)


def test_truncated_png_rejected_at_submit_not_delayed_to_render():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    truncated=_landmark_png()[:200]
    masks=json.dumps({'0':_rect_mask_spec((10,10,20,20))})
    response=client.post('/api/watercolour', files=[('files',('bad.png',truncated,'image/png'))], data={'masks':masks})
    assert response.status_code == 400, response.text
    assert 'bad.png' in response.json()['detail']


def test_rotated_exif_image_bounds_computed_on_transposed_size():
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    exif=Image.Exif(); exif[274]=6
    out=BytesIO()
    Image.new('RGB',(300,400),(80,140,210)).save(out,'JPEG',exif=exif.tobytes())
    raw=out.getvalue()
    # Native pixels are 300x400; orientation 6 transposes to 400x300.
    only_valid_transposed=json.dumps({'0':_rect_mask_spec((310,10,50,20))})
    response=client.post('/api/watercolour', files=[('files',('rotated.jpg',raw,'image/jpeg'))], data={'masks':only_valid_transposed})
    assert response.status_code == 200, response.text
    only_valid_native=json.dumps({'0':_rect_mask_spec((10,310,20,50))})
    response_native=client.post('/api/watercolour', files=[('files',('rotated.jpg',raw,'image/jpeg'))], data={'masks':only_valid_native})
    assert response_native.status_code == 400, response_native.text


def test_cancel_after_png_encoding_still_discards_the_item():
    import threading, time
    from pathlib import Path
    from obed_edom.web.app import app
    from obed_edom.web import watercolour as web_watercolour
    from fastapi.testclient import TestClient
    client=TestClient(app)
    real_convert=web_watercolour.convert
    started=threading.Event()
    calls={'n':0}
    def fake_convert(raw, options, mask=None, *, cancel=None):
        calls['n']+=1
        if calls['n']==2:
            payload,size=real_convert(raw, options, mask, cancel=None)
            started.set()
            deadline=time.time()+5
            while time.time()<deadline and not (cancel and cancel()):
                time.sleep(0.01)
            from obed_edom.watercolour import WatercolourCancelled
            if cancel and cancel():
                raise WatercolourCancelled()
            return payload, size
        return real_convert(raw, options, mask, cancel=cancel)
    web_watercolour.convert=fake_convert
    try:
        files=[('files',(f'{i}.png',png((80+i,90,100,255)),'image/png')) for i in range(3)]
        response=client.post('/api/watercolour', files=files)
        assert response.status_code == 200, response.text
        job_id=response.json()['id']
        assert started.wait(5)
        cancel_response=client.post(f'/api/watercolour/{job_id}/cancel')
        assert cancel_response.status_code == 200
        job=None
        for _ in range(200):
            job=client.get(f'/api/jobs/{job_id}').json()
            if job['status'] in {'done','error'}: break
            time.sleep(0.03)
        items=job['result']['items']
        assert items[0]['status'] == 'done'
        assert items[1]['status'] == 'cancelled'
        result_dir=Path(job['result']['resultDir'])
        assert not list(result_dir.glob('01-*'))
    finally:
        web_watercolour.convert=real_convert


def test_cancel_immediately_after_result_replace_discards_the_committed_file():
    import threading, time
    from pathlib import Path
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    client=TestClient(app)
    committed=threading.Event()
    release=threading.Event()
    original_replace=Path.replace
    calls={'n':0}
    def spying_replace(self, target):
        result=original_replace(self, target)
        if str(target).endswith('-watercolour.png'):
            calls['n']+=1
            if calls['n']==1:
                committed.set()
                release.wait(5)
        return result
    import unittest.mock as mock
    with mock.patch.object(Path, 'replace', spying_replace):
        files=[('files',(f'{i}.png',png((80+i,90,100,255)),'image/png')) for i in range(2)]
        response=client.post('/api/watercolour', files=files)
        assert response.status_code == 200, response.text
        job_id=response.json()['id']
        assert committed.wait(5)
        cancel_response=client.post(f'/api/watercolour/{job_id}/cancel')
        assert cancel_response.status_code == 200
        release.set()
        job=None
        for _ in range(200):
            job=client.get(f'/api/jobs/{job_id}').json()
            if job['status'] in {'done','error'}: break
            time.sleep(0.03)
        items=job['result']['items']
        assert items[0]['status'] == 'cancelled'
        result_dir=Path(job['result']['resultDir'])
        assert not list(result_dir.glob('00-*'))

def test_renamed_watercolour_job_still_serves_result_file_and_download():
    from pathlib import Path
    from obed_edom.web.app import app
    from fastapi.testclient import TestClient
    import time
    client = TestClient(app)
    response = client.post('/api/watercolour', files=[('files', ('good.png', png((90, 140, 210, 255)), 'image/png'))])
    assert response.status_code == 200, response.text
    job_id = response.json()['id']
    for _ in range(80):
        job = client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in {'done', 'error'}:
            break
        time.sleep(.03)
    old_output_dir = Path(job['result']['outputDir'])
    item_id = job['result']['items'][0]['id']

    target = f'quiet-jordan-{job_id}'
    renamed = client.patch(f'/api/jobs/{job_id}/name', json={'name': target})
    assert renamed.status_code == 200, renamed.text
    new_output_dir = Path(renamed.json()['result']['outputDir'])
    assert new_output_dir.name == target
    assert not old_output_dir.exists()

    assert client.get(f'/api/watercolour/{job_id}/items/{item_id}/result').status_code == 200
    assert client.get(f'/api/watercolour/{job_id}/download').status_code == 200
