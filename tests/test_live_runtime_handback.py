"""Magic Move hand-back geometry (keynote_live_handback_geometry.plan.md §5 items 2-3).

R6-R8 crossfade a Magic Move leaf that scales without a Keynote `contents` animation to its matched next-slide
texture, so the settled GL frame is the DOM frame. These tests run the real `fB.setupTexture` (+ R6's method) and
`QB.renderFrameWithContext` cut out of the stock and patched player on the committed P2 1->2 effect and slide-2 layer
tree, and pin a Python mirror of the R6 rule (the census) to the real bytes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import subprocess
from pathlib import Path

import pytest

from obed_edom import live_runtime
from tests.test_live_runtime import (
    EFFECT_1_TO_2,
    FIXTURE_ROOT,
    MAIN_OUTPUT,
    REAL_PLAYER,
    _cut,
    _hook_only,
    _node,
    _real_player,
    _signature,
)

SLIDE2_LAYERS = FIXTURE_ROOT / "slide2_layers.json"
MM = "apple:magic-move-implied-motion-path"
# Slots are eB draw order (effect.textures). Slot 2 is the black sentinel, slot 4 the green square.
SENTINEL, GREEN = 2, 4
SOURCE = {SENTINEL: "SANITIZED-TEXTURE-0", GREEN: "SANITIZED-TEXTURE-2"}
DESTINATION = {SENTINEL: "SANITIZED-TEXTURE-5", GREEN: "SANITIZED-TEXTURE-9"}
PERCENTS = (0, 0.5, 1)
SCALE_ONLY = b"1===sx&&1===sy&&(ok=!1);"
ANY_GEOMETRY = b"1===sx&&1===sy&&0===tx&&0===ty&&(ok=!1);"


def _texture_ids(node) -> set[str]:
    if isinstance(node, dict):
        ids = {node["texture"]} if isinstance(node.get("texture"), str) else set()
        for value in node.values():
            ids |= _texture_ids(value)
        return ids
    if isinstance(node, list):
        return set().union(*(_texture_ids(value) for value in node)) if node else set()
    return set()


def _run(player: bytes, effect: dict, slide2: dict, *, cached: bool = True, destination_ids=None,
         extra_source_ids=()) -> list[dict]:
    """Per eB slot: R6's `obedMix`, the `toTexture` set up, and per percent the texture bound on each unit and the
    `mixFactor` set by `QB`. `R.createTexture` returns the asset itself; easing is stubbed linear and the matrix helpers
    are identity. `isBlending` mirrors `eB.prepareAnimationWithContext` (`!!texture.toTexture`)."""
    source = player.decode()
    qb = _cut(source, "class QB{", "class eB{")
    fb = _cut(source, "setupTexture(A){", "draw(A){if(A.baseLayer)")
    config = {
        "effect": effect,
        "slide2": slide2,
        "cached": cached,
        "source": sorted(_texture_ids(effect) | set(extra_source_ids)),
        "destination": sorted(_texture_ids(slide2) if destination_ids is None else destination_ids),
        "percents": PERCENTS,
    }
    script = """
class kA{doubleForAnimationCurve(n,x){return x}}
class KA{}
const u={translateMatrix4:(m)=>m,rotateMatrix4AboutXYZ:(m)=>m,scaleMatrix4:(m)=>m};
const R={createTexture:(gl,asset)=>asset};
%s
class F{constructor(t){this.textureAssets=t;this.gl={}}%s}
function vb(l){const t=l.initialState,a=t.anchorPoint;
  const x=Math.round(1e6*(t.position.pointX-t.width/2-(a.pointX-.5)*t.width))/1e6,
        y=Math.round(1e6*(t.position.pointY-t.height/2-(a.pointY-.5)*t.height))/1e6;
  return {textureId:l.texture?l.texture:null,animations:l.animations,initialState:t,texturedRectangle:l.texturedRectangle,
    hasHighlightedBulletAnimation:l.hasHighlightedBulletAnimation,bounds:{width:t.width,height:t.height,offset:{pointX:x,pointY:y}},
    layers:(l.layers||[]).map(vb)}}
const cfg=%s;
const assets=(ids)=>Object.fromEntries(ids.map((id)=>[id,'asset:'+id]));
const src=assets(cfg.source),dst=assets(cfg.destination);
var UC={script:{slideList:['s1','s2'],loopSlideshow:false,slides:{s1:{events:[]},s2:{events:[{baseLayer:cfg.slide2}]}}},
  textureManager:{slideCache:cfg.cached?{0:{textureAssets:src},1:{textureAssets:dst}}:{0:{textureAssets:src}}}};
const e=cfg.effect;
const infos=new F(src).setupTexture({name:e.name,kpfLayer:vb(e.baseLayer),baseLayer:e.baseLayer});
console.log(JSON.stringify(infos.map((t)=>({mix:!!t.obedMix,to:t.toTexture||null,
  frames:t.animations&&t.animations.length?cfg.percents.map((percent)=>{
    const units={};let unit=0,mix=null;
    const gl={blendFunc(){},activeTexture(x){unit=x},bindTexture(_,x){units[unit]=x},ONE:1,ONE_MINUS_SRC_ALPHA:2,TEXTURE0:0,TEXTURE1:1,TEXTURE_2D:3};
    const shader={setGLFloat(v,n){if(n==='mixFactor')mix=v},setMat4WithTransform3D(){}};
    new QB(gl).renderFrameWithContext(shader,{drawWithShader(){}},
      {textureInfo:t,effectDuration:1000*e.duration,baseTransform:[],percent,isBlending:!!t.toTexture});
    return {units,mix}}):null}))));
""" % (qb, fb, json.dumps(config))
    result = subprocess.run([_node(), "-e", script], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def _fixtures() -> tuple[dict, dict]:
    return json.loads(EFFECT_1_TO_2.read_text()), json.loads(SLIDE2_LAYERS.read_text())


def _mixed(slots: list[dict]) -> list[int]:
    return [index for index, slot in enumerate(slots) if slot["mix"]]


def _leaf(node: dict, texture: str) -> dict:
    if node.get("texture") == texture:
        return node
    for child in node.get("layers") or []:
        found = _leaf(child, texture)
        if found:
            return found
    return {}


def _patched(player: bytes) -> bytes:
    return live_runtime.patch_player(player)


def test_real_patched_methods_crossfade_only_the_scaled_leaves_of_p2_1_to_2():
    player = _real_player()
    effect, slide2 = _fixtures()
    stock = _run(_hook_only(player), effect, slide2)
    patched = _run(_patched(player), effect, slide2)
    assert len(stock) == len(patched) == 5
    assert _mixed(stock) == [] and _mixed(patched) == [SENTINEL, GREEN]
    for slot in (SENTINEL, GREEN):
        src, dst = "asset:" + SOURCE[slot], "asset:" + DESTINATION[slot]
        assert stock[slot]["to"] is None
        assert stock[slot]["frames"] == [{"units": {"0": src}, "mix": None}] * 3
        assert patched[slot]["to"] == dst
        # Unit 0 keeps the slide-1 texture; unit 1 holds the matched slide-2 texture and the mix follows the move:
        # p = 0 draws the source (start unchanged), p = 1 draws the destination (the DOM's texture).
        assert patched[slot]["frames"] == [{"units": {"0": src, "1": dst}, "mix": percent} for percent in PERCENTS]
    for slot in (0, 1, 3):
        assert patched[slot] == stock[slot]
    # Slot 0 is Keynote's own `contents` crossfade, untouched.
    assert stock[0]["to"] is not None and stock[0]["frames"][-1]["mix"] == 1
    # The dashboard preview's bytes behave the same.
    assert _run(live_runtime.patch_rendering(player), effect, slide2) == patched
    assert _mirror_slots(effect, slide2) == [SENTINEL, GREEN]


def _fade(effect, slide2):
    for animation in _leaf(effect["baseLayer"], SOURCE[GREEN])["animations"][0]["animations"]:
        if animation["property"] == "opacity":
            animation["to"]["scalar"] = animation["from"]["scalar"] / 2
            return {}
    raise AssertionError("green leaf has no opacity animation")


def _hidden_destination(effect, slide2):
    _leaf(slide2, DESTINATION[GREEN])["initialState"]["hidden"] = True
    return {}


def _ambiguous(effect, slide2):
    twin = copy.deepcopy(next(layer for layer in slide2["layers"] if _leaf(layer, DESTINATION[GREEN])))
    _leaf(twin, DESTINATION[GREEN])["texture"] = "SANITIZED-TEXTURE-TWIN"
    slide2["layers"].append(twin)
    return {}


def _missing_cache(effect, slide2):
    return {"cached": False}


def _missing_destination_texture(effect, slide2):
    return {"destination_ids": sorted(_texture_ids(slide2) - {DESTINATION[GREEN]})}


def _contents(effect, slide2):
    group = _leaf(effect["baseLayer"], SOURCE[GREEN])["animations"][0]
    group["animations"].append({"property": "contents", "from": {"texture": SOURCE[GREEN]},
                                "to": {"texture": DESTINATION[GREEN]}, "beginTime": 0,
                                "duration": group["duration"], "fillMode": "both", "timingFunction": "Linear"})
    # Keynote ships a `contents` destination in the source slide's assets (as at 3->4).
    return {"extra_source_ids": [DESTINATION[GREEN]]}


def _translation_only(effect, slide2):
    """Drop the green leaf's scale and add a visible slide-2 leaf exactly on its translated rect, so only the
    scale-only rule (decision 5b) refuses it."""
    leaf = _leaf(effect["baseLayer"], SOURCE[GREEN])
    group = leaf["animations"][0]
    group["animations"] = [a for a in group["animations"] if not a["property"].startswith("transform.scale")]
    translation = next(a for a in group["animations"] if a["property"] == "transform.translation")["to"]
    x, y = _offset_to(effect["baseLayer"], SOURCE[GREEN])
    state = copy.deepcopy(leaf["initialState"])
    state["hidden"] = False
    state["position"] = {"pointX": x + translation["pointX"] + state["anchorPoint"]["pointX"] * state["width"],
                         "pointY": y + translation["pointY"] + state["anchorPoint"]["pointY"] * state["height"]}
    slide2["layers"].append({"initialState": state, "animations": [], "texture": "SANITIZED-TEXTURE-MOVED",
                             "texturedRectangle": leaf.get("texturedRectangle")})
    return {}


def _offset_to(node: dict, texture: str, x: float = 0.0, y: float = 0.0):
    dx, dy = _vb_offset(node)
    x, y = x + dx, y + dy
    if node.get("texture") == texture:
        return x, y
    for child in node.get("layers") or []:
        found = _offset_to(child, texture, x, y)
        if found:
            return found
    return None


# Each case edits the fixtures and says which slots must still crossfade; every other slot must match stock.
STOCK_CASES = {
    "fade": (_fade, [SENTINEL]),
    "hidden-destination": (_hidden_destination, [SENTINEL]),
    "ambiguous-match": (_ambiguous, [SENTINEL]),
    "missing-cache": (_missing_cache, []),
    "missing-destination-texture": (_missing_destination_texture, [SENTINEL]),
    "contents-leaf": (_contents, [SENTINEL]),
    "translation-only": (_translation_only, [SENTINEL]),
}


@pytest.mark.parametrize("name", STOCK_CASES)
def test_real_patched_methods_keep_non_qualifying_leaves_stock(name):
    player = _real_player()
    effect, slide2 = _fixtures()
    edit, expected = STOCK_CASES[name]
    kwargs = edit(effect, slide2)
    stock = _run(_hook_only(player), effect, slide2, **kwargs)
    patched = _run(_patched(player), effect, slide2, **kwargs)
    assert _mixed(patched) == expected
    for slot, (old, new) in enumerate(zip(stock, patched)):
        if slot not in expected:
            assert new == old, slot
    assert _mirror_slots(effect, slide2, cached=kwargs.get("cached", True),
                         destination_ids=kwargs.get("destination_ids")) == expected


def test_translation_only_leaf_is_refused_by_the_scale_only_rule_not_by_the_match():
    # Positive control for the case above: the plan's rev-1 "any geometry change" rule engages on the same inputs.
    player = _real_player()
    effect, slide2 = _fixtures()
    _translation_only(effect, slide2)
    patched = _patched(player)
    assert patched.count(SCALE_ONLY) == 1
    any_geometry = patched.replace(SCALE_ONLY, ANY_GEOMETRY)
    assert _mixed(_run(any_geometry, effect, slide2)) == [SENTINEL, GREEN]
    assert _mixed(_run(patched, effect, slide2)) == [SENTINEL]


# Census mirror of R6 in Python (JS `Math.round` = floor(x + 0.5)); cross-checked against the real bytes above.


def _js_round6(value: float) -> float:
    return math.floor(1e6 * value + 0.5) / 1e6


def _vb_offset(node: dict) -> tuple[float, float]:
    state, anchor = node["initialState"], node["initialState"]["anchorPoint"]
    return (
        _js_round6(state["position"]["pointX"] - state["width"] / 2 - (anchor["pointX"] - 0.5) * state["width"]),
        _js_round6(state["position"]["pointY"] - state["height"] / 2 - (anchor["pointY"] - 0.5) * state["height"]),
    )


def _source_leaves(node: dict, x: float = 0.0, y: float = 0.0, out=None) -> list:
    """`fB.textureInfoFromEffect` order: (leaf, offset x, offset y)."""
    out = [] if out is None else out
    dx, dy = _vb_offset(node)
    x, y = x + dx, y + dy
    if node.get("texture"):
        out.append((node, x, y))
    else:
        for child in node.get("layers") or []:
            _source_leaves(child, x, y, out)
    return out


def _destination_leaves(node: dict, x: float = 0.0, y: float = 0.0, out=None) -> list:
    out = [] if out is None else out
    state, anchor = node["initialState"], node["initialState"]["anchorPoint"]
    x = x + _js_round6(state["position"]["pointX"] - anchor["pointX"] * state["width"])
    y = y + _js_round6(state["position"]["pointY"] - anchor["pointY"] * state["height"])
    if node.get("texture") and not state.get("hidden"):
        out.append((node["texture"], x, y, state["width"], state["height"]))
    for child in node.get("layers") or []:
        _destination_leaves(child, x, y, out)
    return out


def _has_contents(leaf: dict) -> bool:
    animations = leaf.get("animations") or []
    if not animations:
        return False
    first = animations[0]
    if first.get("property") == "contents":
        return True
    return not first.get("property") and any(a.get("property") == "contents" for a in first.get("animations") or [])


def _mirror_slots(effect: dict, destination: dict | None, *, cached: bool = True, destination_ids=None) -> list[int]:
    if not cached or destination is None:
        return []
    available = _texture_ids(destination) if destination_ids is None else set(destination_ids)
    try:
        targets = _destination_leaves(destination)
    except (KeyError, TypeError):
        return []  # R6's try/catch: a malformed destination tree leaves the whole effect stock.
    slots = []
    for slot, (leaf, x, y) in enumerate(_source_leaves(effect["baseLayer"])):
        state = leaf["initialState"]
        animations = leaf.get("animations") or []
        group = animations[0].get("animations") if animations else None
        if _has_contents(leaf) or group is None or state.get("scale") != 1:
            continue
        sx = sy = 1
        tx = ty = 0
        ok = True
        for animation in group:
            prop = animation.get("property")
            if prop == "transform.scale.x":
                sx = animation["to"]["scalar"]
            elif prop == "transform.scale.y":
                sy = animation["to"]["scalar"]
            elif prop == "transform.translation":
                tx, ty = animation["to"]["pointX"], animation["to"]["pointY"]
            elif not (prop == "opacity" and animation["from"]["scalar"] == animation["to"]["scalar"]):
                ok = False
        if sx == 1 and sy == 1:
            ok = False
        width, height = state["width"], state["height"]
        ax, ay = state["anchorPoint"]["pointX"] * width, state["anchorPoint"]["pointY"] * height
        quad = (x + tx + ax - sx * ax, y + ty + ay - sy * ay, sx * width, sy * height)
        matches = [t for t in targets if all(abs(a - b) <= 0.01 for a, b in zip(t[1:], quad))]
        if ok and len(matches) == 1 and matches[0][0] != leaf["texture"] and matches[0][0] in available:
            slots.append(slot)
    return slots


def _magic_moves(roots) -> list[tuple[dict, dict | None]]:
    """(effect, destination events[0].baseLayer or None) for every Magic Move under the export roots."""
    pairs = []
    for root in roots:
        header = json.loads((root / "header.json").read_text())
        slides = header["slideList"]
        for index, slide in enumerate(slides):
            try:
                data = json.loads((root / slide / f"{slide}.json").read_text())
            except (OSError, ValueError):
                continue
            following = index + 1 if index + 1 < len(slides) else 0 if header.get("loopSlideshow") else None
            destination = None
            if following is not None:
                try:
                    events = json.loads((root / slides[following] / f"{slides[following]}.json").read_text())["events"]
                    destination = events[0]["baseLayer"] if events else None
                except (OSError, ValueError, KeyError):
                    destination = None
            for event in data.get("events") or []:
                for effect in event.get("effects") or []:
                    if effect.get("name") == MM and "baseLayer" in effect:
                        pairs.append((effect, destination))
    return pairs


def _census(pairs) -> tuple[dict[str, int], set[tuple[bool, int]]]:
    reference = _signature(json.loads(EFFECT_1_TO_2.read_text()))
    seen, stats, affected = set(), {"effects": 0, "leaves": 0, "one_to_two": 0}, set()
    for effect, destination in pairs:
        digest = hashlib.sha1(json.dumps([effect, destination], sort_keys=True).encode()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        is_one_to_two = _signature(effect) == reference
        stats["effects"] += 1
        stats["one_to_two"] += is_one_to_two
        stats["leaves"] += len(_source_leaves(effect["baseLayer"]))
        affected |= {(is_one_to_two, slot) for slot in _mirror_slots(effect, destination)}
    return stats, affected


def test_handback_census_mirror_affects_only_p2_1_to_2_slots_2_and_4_in_committed_fixtures():
    effect, slide2 = _fixtures()
    roots = sorted(header.parent for header in FIXTURE_ROOT.rglob("assets/header.json"))
    pairs = [(effect, slide2)] + _magic_moves(roots)
    stats, affected = _census(pairs)
    assert stats["one_to_two"] >= 1 and stats["effects"] > stats["one_to_two"]
    assert affected == {(True, SENTINEL), (True, GREEN)}


@pytest.mark.skipif(not MAIN_OUTPUT.is_dir(), reason="main checkout output/ not available")
def test_handback_census_mirror_affects_only_p2_1_to_2_slots_2_and_4_across_real_exports():
    roots = sorted(header.parent for header in MAIN_OUTPUT.rglob("assets/header.json"))
    pairs = _magic_moves(roots)
    if not pairs:
        pytest.skip("no real exports under output/")
    stats, affected = _census(pairs)
    assert stats["one_to_two"] >= 1 and stats["effects"] > stats["one_to_two"]
    assert affected == {(True, SENTINEL), (True, GREEN)}


# R8 (decision 3b): at idle, `preloadTextures` resolves B (the next scene in `IdleAtFinalState`, else the current one)
# and loads its slide; the patch also loads scene B+1's slide only when event B is a Magic Move, so R6 finds the
# destination cached at MM setup. P2 scenes: slide 1 = 0-1 (movie, MM 1->2), slide 2 = 2-5 (builds, dissolve 2->3),
# slide 3 = 6-7 (movie, MM 3->4), slide 4 = 8-9 (movie, dissolve).
FINAL, INITIAL = "IdleAtFinalState", "IdleAtInitialState"


def _p2_events(root: Path = FIXTURE_ROOT / "assets") -> list[dict]:
    events = []
    for slide in json.loads((root / "header.json").read_text())["slideList"]:
        data = json.loads((root / slide / f"{slide}.json").read_text())
        events += [{"effects": [{"name": e["name"]} for e in event["effects"]]} for event in data["events"]]
    return events


def _preload(player: bytes, events: list[dict], states: list[tuple[str, int]], loop: bool = False) -> list[list[int]]:
    """Scenes passed to `textureManager.loadScene` by the real `preloadTextures`, per (state, currentSceneIndex)."""
    method = _cut(player.decode(), "preloadTextures(){", "unloadTextures(){")
    script = """
const tg="IdleAtFinalState";
class P{%s}
const script={events:%s,loopSlideshow:%s};script.numScenes=script.events.length;
console.log(JSON.stringify(%s.map(([state,scene])=>{const loads=[];const p=new P();
  Object.assign(p,{script,state,currentSceneIndex:scene,textureManager:{loadScene:(s)=>loads.push(s)}});
  p.preloadTextures();return loads})));
""" % (method, json.dumps(events), "true" if loop else "false", json.dumps(states))
    result = subprocess.run([_node(), "-e", script], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def test_real_preload_adds_the_next_slide_only_before_a_magic_move_on_p2():
    player = _real_player()
    events = _p2_events()
    assert events == _p2_events(REAL_PLAYER.parents[1])
    assert [event["effects"][0]["name"] == MM for event in events] == [
        False, True, False, False, False, False, False, True, False, False]
    states = [(state, scene) for state in (INITIAL, FINAL) for scene in range(len(events))]
    stock = _preload(_hook_only(player), events, states)
    patched = _preload(_patched(player), events, states)
    extra = {}
    for state, old, new in zip(states, stock, patched):
        assert new[: len(old)] == old
        if len(new) > len(old):
            extra[state] = new[len(old):]
    # Idle on slide 1 before 1->2 and on slide 3 before 3->4 (settled after the movie build, or restarted at the
    # MM scene by a go-to); never while idle on slide 2 before the 2->3 dissolve, nor on slide 4.
    assert extra == {(FINAL, 0): [2], (INITIAL, 1): [2], (FINAL, 6): [8], (INITIAL, 7): [8]}
    assert _preload(live_runtime.patch_rendering(player), events, states) == patched
    assert _preload(live_runtime.patch_player(player, mm_opacity=False), events, states) == stock


def test_real_preload_at_the_last_scene_and_across_a_loop_wrap():
    player = _real_player()
    movie, mm = {"effects": [{"name": "apple:movie-start"}]}, {"effects": [{"name": MM}]}
    # A deck whose last event is a Magic Move: without a loop there is no next scene to load.
    last = [movie, movie, mm]
    assert _preload(_patched(player), last, [(FINAL, 1), (INITIAL, 2), (FINAL, 2)]) == [[2], [2], [2]]
    # Looping: at the last scene the player wraps B to 0; R8 follows event 0, and never loads past the wrap.
    looped = [mm, movie, mm]
    stock = _preload(_hook_only(player), looped, [(FINAL, 2), (FINAL, 1)], loop=True)
    patched = _preload(_patched(player), looped, [(FINAL, 2), (FINAL, 1)], loop=True)
    assert stock == [[0], [2]]
    assert patched == [[0, 1], [2]]
    assert _preload(_patched(player), [movie, movie], [(FINAL, 1)], loop=True) == [[0]]
    # No script events at a negative scene (before the first `setCurrentSceneIndexTo`): stock load only.
    assert _preload(_patched(player), last, [(INITIAL, -1)]) == [[-1]]
