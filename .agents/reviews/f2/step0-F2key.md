# Step 0a/0b record — F2.key (owner-authored, 9 slides) and its raw HTML export

2026-10-14. Deck `~/Desktop/Convert wall to 16x9 CGs/F2.key`; export `…/F2-html/` via `html_preview.export_html` (owner-run; Keynote peak RSS 1.51 GB). Player sha `17c0c938`. Offline reads only.

## Step 0a — authored deck (IWA)
```
canvas (1920.0, 1080.0) slides 9

## slide 1: transition apple:dissolve 1.5s dir=None auto=False {}
   fill slide={}  master={}
   build 1: com.apple.iWork.Keynote.KLNSparkle In 2.0s start=On click delay=0.0 dir=None target=text 'He stood between the living an'
   build 2: com.apple.iWork.Keynote.KLNSparkle In 1.25s start=On click delay=0.0 dir=None target=text 'the plague stopped'
   objects 5: {'ShapeInfoArchive': 4, 'ImageArchive': 1}

## slide 2: transition com.apple.iWork.Keynote.BUKFlop 1.0s dir=None auto=False {}
   fill slide={}  master={}
   objects 9: {'ImageArchive': 5, 'ShapeInfoArchive': 4}

## slide 3: transition apple:magic-move-implied-motion-path 1.5s dir=None auto=False {'customTimingCurve': 'TransitionCustomAttributesTimingCurveTypeEaseInEaseOut'}
   fill slide={}  master={}
   build 1: com.apple.iWork.Keynote.BUKAnvil In 2.0s start=After prev delay=0.0 dir=None target=image 'Report Card.png'
   objects 10: {'ImageArchive': 7, 'ShapeInfoArchive': 3}

## slide 4: transition apple:dissolve 1.5s dir=None auto=False {}
   fill slide={}  master={}
   build 1: apple:twist-and-scale In 2.0s start=After prev delay=0.0 dir=32 target=text 'Malaysia'
   objects 10: {'ImageArchive': 5, 'ShapeInfoArchive': 5}

## slide 5: transition apple:wipe-iris 3.0s dir=None auto=False {}
   fill slide={}  master={}
   objects 1: {'ImageArchive': 1}

## slide 6: transition com.apple.iWork.Keynote.BUKTwist 1.5s dir=None auto=False {'customTwist': 3.3}
   fill slide={}  master={}
   objects 1: {'GroupArchive': 1}

## slide 7: transition apple:dissolve 1.5s dir=None auto=False {}
   fill slide={}  master={}
   build 1: apple:movie-start In 0.5s start=After prev delay=0.0 dir=None target=movie 'shutterstock_3637941261.mp4'
   objects 1: {'MovieArchive': 1}
   movie shutterstock_3637941261.mp4 loop=None PA=True trim=0.0-8.76

## slide 8: transition apple:ca-revolve 1.5s dir=13 auto=False {'customBounce': False}
   fill slide={}  master={}
   build 1: apple:dropbuild In 1.0s start=After prev delay=0.01 dir=None target=image 'pasted-image.pdf'
   build 2: apple:movie-start In 0.5s start=With prev delay=0.01 dir=None target=movie 'PIN DROP WAVE.mov'
   build 3: apple:bc-zoom-big character In 1.0s start=With prev delay=0.01 dir=None target=shape ''
   build 4: apple:bc-zoom-big character In 1.0s start=With prev delay=0.01 dir=None target=text 'CHC Di He'
   build 5: apple:wipe-iris In 1.0s start=With prev delay=0.0 dir=None target=image 'Untitled.001.png'
   objects 14: {'ImageArchive': 5, 'ShapeInfoArchive': 8, 'MovieArchive': 1}
   movie PIN DROP WAVE.mov loop=None PA=False trim=0.0-2.64

## slide 9: transition apple:magic-move-implied-motion-path 1.5s dir=None auto=False {'customTimingCurve': 'TransitionCustomAttributesTimingCurveTypeEaseInEaseOut'}
   fill slide={}  master={}
   build 1: apple:movie-start In 0.5s start=On click delay=0.0 dir=None target=movie 'Untitled-H264.mov'
   objects 1: {'MovieArchive': 1}
   movie Untitled-H264.mov loop=None PA=True trim=0.0-46.033333
```

## Step 0b — export census
# Census run

| Source | Type | Effect | Count |
|---|---|---|---:|
| fixtures | buildIn | `apple:bc-zoom-big character` | 2 |
| fixtures | buildIn | `apple:dropbuild` | 1 |
| fixtures | buildIn | `apple:movie-start` | 3 |
| fixtures | buildIn | `apple:twist-and-scale` | 1 |
| fixtures | buildIn | `apple:wipe-iris` | 1 |
| fixtures | buildIn | `com.apple.iWork.Keynote.BUKAnvil` | 1 |
| fixtures | buildIn | `com.apple.iWork.Keynote.KLNSparkle` | 2 |
| fixtures | buildIn | `renderMovie` | 3 |
| fixtures | transition | `apple:ca-revolve` | 1 |
| fixtures | transition | `apple:dissolve` | 3 |
| fixtures | transition | `apple:magic-move-implied-motion-path` | 2 |
| fixtures | transition | `apple:wipe-iris` | 1 |
| fixtures | transition | `com.apple.iWork.Keynote.BUKFlop` | 1 |
| fixtures | transition | `com.apple.iWork.Keynote.BUKTwist` | 1 |

| Source | Export root (relative to source) | Transitions | Other effects |
|---|---|---:|---:|
| fixtures | `.` | 9 | 14 |

Export roots: 1; effect occurrences: 23; read/schema errors: 0.

N = untextured layer; T = textured layer; V = video flag; braces = animation properties (group included); brackets = children in order.

Full source paths, SHA-256, JSON pointers, attributes, initial states and animation trees: `census_f2.json`.
One occurrence per row, with shape/timing: `census_f2_rows.tsv`. Missing timing is recorded as `<absent>`, not inferred.

# Shape and timing variants

| Type / name | Count | Shape | Effect duration (s) | Animation durations (s) | Timing functions | fillMode | First source anchor |
|---|---:|---|---|---|---|---|---|
| `buildIn / apple:bc-zoom-big character` | 2 | `N[N[T{group,hidden,opacity,transform.scale.xy}]]` | `1` | `["0.7","0.9999","1"]` | `["\"<absent>\"","\"EaseInEaseOut\"","\"custom\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/29A80700-2E22-4F5A-8CC1-934BEE748D1C/29A80700-2E22-4F5A-8CC1-934BEE748D1C.json#/events/0/effects/2` |
| `buildIn / apple:dropbuild` | 1 | `N[N[T{group,hidden,transform.translation.y}]]` | `1` | `["0.9999","1"]` | `["\"<absent>\"","{\"timingControlPoint1x\":0.30064624547958374,\"timingControlPoint1y\":0.09829729050397873,\"timingControlPoint2x\":0.8997974395751953,\"timingControlPoint2y\":0.5973872542381287,\"timingFunction\":\"custom\"}","{\"timingControlPoint1x\":0.4557388126850128,\"timingControlPoint1y\":0.873240053653717,\"timingControlPoint2x\":0.7058159708976746,\"timingControlPoint2y\":1,\"timingFunction\":\"custom\"}"]` | `["\"both\"","\"forwards\"","\"removed\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/29A80700-2E22-4F5A-8CC1-934BEE748D1C/29A80700-2E22-4F5A-8CC1-934BEE748D1C.json#/events/0/effects/0` |
| `buildIn / apple:movie-start` | 3 | `N[N[T{group,hidden,isPlaying}]]` | `0.001` | `["0.001"]` | `["\"<absent>\""]` | `["\"both\"","\"removed\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/1FCB8DBB-82EA-44BD-A2FB-7846FE665E5D/1FCB8DBB-82EA-44BD-A2FB-7846FE665E5D.json#/events/0/effects/0` |
| `buildIn / apple:twist-and-scale` | 1 | `N[N[T{group,hidden,opacity,transform}],N[T{group,hidden,opacity,transform}],N[T{group,hidden,opacity,transform}],N[T{group,hidden,opacity,transform}],N[T{group,hidden,opacity,transform}],N[T{group,hidden,opacity,transform}],N[T{group,hidden,opacity,transform}],N[T{group,hidden,opacity,transform}]]` | `2` | `["0.2","1.7045757474971686","1.8420861679928981","1.8658256936410385","1.8932659121702333","1.9302262224408484","1.9537774784820447","1.9592233529219367","1.9891311313969808","1.999","2"]` | `["\"<absent>\"","\"custom\""]` | `["\"both\"","\"forwards\"","\"removed\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/2C214651-FBDF-4698-B8D4-A16E2D803A56/2C214651-FBDF-4698-B8D4-A16E2D803A56.json#/events/0/effects/0` |
| `buildIn / apple:wipe-iris` | 1 | `N[N[T{group,hidden,opacity}]]` | `1` | `["1"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/29A80700-2E22-4F5A-8CC1-934BEE748D1C/29A80700-2E22-4F5A-8CC1-934BEE748D1C.json#/events/0/effects/4` |
| `buildIn / com.apple.iWork.Keynote.BUKAnvil` | 1 | `N[N[T{group,hidden,opacity}]]` | `2` | `["2"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/6B05DE14-37DB-4505-B242-8996669A30BD/6B05DE14-37DB-4505-B242-8996669A30BD.json#/events/0/effects/0` |
| `buildIn / com.apple.iWork.Keynote.KLNSparkle` | 1 | `N[N[T{group,hidden,opacity}]]` | `1.25` | `["1.25"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/628CFD5E-D50E-4C46-8882-42A7505D74FA/628CFD5E-D50E-4C46-8882-42A7505D74FA.json#/events/1/effects/0` |
| `buildIn / com.apple.iWork.Keynote.KLNSparkle` | 1 | `N[N[T{group,hidden,opacity}]]` | `2` | `["2"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/628CFD5E-D50E-4C46-8882-42A7505D74FA/628CFD5E-D50E-4C46-8882-42A7505D74FA.json#/events/0/effects/0` |
| `buildIn / renderMovie` | 1 | `N[T,TV,T]` | `0` | `[]` | `[]` | `[]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/271371F9-08BC-4095-A016-B35F3831D11C/271371F9-08BC-4095-A016-B35F3831D11C.json#/events/0/effects/0/effects/0` |
| `buildIn / renderMovie` | 2 | `N[T,TV]` | `0` | `[]` | `[]` | `[]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/1FCB8DBB-82EA-44BD-A2FB-7846FE665E5D/1FCB8DBB-82EA-44BD-A2FB-7846FE665E5D.json#/events/0/effects/0/effects/0` |
| `transition / apple:ca-revolve` | 1 | `N[N[N[T{hidden}],N[T{opacity}]],N[N[T{anchorPointZ,doubleSided,group,hidden,opacity,transform.rotation.x,zPosition}]],N[N[T{anchorPointZ,doubleSided,group,hidden,opacity,transform.rotation.x,zPosition}]],N[N[T{anchorPointZ,doubleSided,group,hidden,opacity,transform.rotation.x,zPosition}]],N[N[T{anchorPointZ,doubleSided,group,hidden,opacity,transform.rotation.x,zPosition}]],N[N[T{anchorPointZ,doubleSided,group,hidden,opacity,transform.rotation.x,zPosition}]],N[N[T{anchorPointZ,doubleSided,group,hidden,opacity,transform.rotation.x,zPosition}]],N[N[T{anchorPointZ,doubleSided,group,hidden,opacity,transform.rotation.x,zPosition}]],N[N[T{anchorPointZ,doubleSided,group,hidden,opacity,transform.rotation.x,zPosition}]],N[N[T{anchorPointZ,doubleSided,group,hidden,opacity,transform.rotation.x,zPosition}]],N[N[T{anchorPointZ,doubleSided,group,hidden,opacity,transform.rotation.x,zPosition}]],N[N[T{anchorPointZ,doubleSided,group,hidden,opacity,transform.rotation.x,zPosition}]],N[N[T{anchorPointZ,doubleSided,group,hidden,opacity,transform.rotation.x,zPosition}]],N[N[T{anchorPointZ,doubleSided,group,hidden,opacity,transform.rotation.x,zPosition}]],N[N[T{anchorPointZ,doubleSided,group,hidden,opacity,transform.rotation.x,zPosition}]],N[N[T{anchorPointZ,doubleSided,group,hidden,opacity,transform.rotation.x,zPosition}]]]` | `1.5` | `["1.2963785861307568","1.3886517406774708","1.4042700139579105","1.4109522901826852","1.4118406178725005","1.4146467490827788","1.4171659808136798","1.417440941632791","1.4265373475804894","1.4503968692507678","1.4597509409651874","1.4690309392963636","1.4704057734146545","1.4720865797501839","1.4890378259582644","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\"","{\"timingControlPoint1x\":0,\"timingControlPoint1y\":0,\"timingControlPoint2x\":0.9950631260871887,\"timingControlPoint2y\":0.9961773753166199,\"timingFunction\":\"custom\"}","{\"timingControlPoint1x\":0.015217834152281284,\"timingControlPoint1y\":0.004324234090745449,\"timingControlPoint2x\":0.9610611200332642,\"timingControlPoint2y\":0.9601569175720215,\"timingFunction\":\"custom\"}","{\"timingControlPoint1x\":0.5190371870994568,\"timingControlPoint1y\":0.002107007661834359,\"timingControlPoint2x\":0.5975098609924316,\"timingControlPoint2y\":1,\"timingFunction\":\"custom\"}","{\"timingControlPoint1x\":0.6491111516952515,\"timingControlPoint1y\":0.5231849551200867,\"timingControlPoint2x\":0.4050056040287018,\"timingControlPoint2y\":1,\"timingFunction\":\"custom\"}","{\"timingFunction\":\"Linear\"}"]` | `["\"both\"","\"removed\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/29A80700-2E22-4F5A-8CC1-934BEE748D1C/29A80700-2E22-4F5A-8CC1-934BEE748D1C.json#/events/1/effects/0` |
| `transition / apple:dissolve` | 3 | `N[N[T,T{opacity}]]` | `1.5` | `["1.5"]` | `["\"EaseInEaseOut\""]` | `["\"both\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/1FCB8DBB-82EA-44BD-A2FB-7846FE665E5D/1FCB8DBB-82EA-44BD-A2FB-7846FE665E5D.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 1 | `N[N[N{group,zPosition}[T{contents,group}]],N{group,opacity,zPosition}[T{contents,group,opacity,transform.scale.x,transform.scale.y,transform.translation}],N{group,zPosition}[T{group,hidden,opacity,transform.rotation.z}],N{group,zPosition}[T{contents,group}],N{group,zPosition}[T{contents,group}],N{group,zPosition}[T{contents,group}],N{group,zPosition}[T],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T{group,hidden,opacity}],N{group,zPosition}[T],N{group,opacity,zPosition}[T{contents,group,opacity,transform.scale.x,transform.scale.y,transform.translation}],N{group,opacity,zPosition}[T{contents,group,opacity,transform.scale.x,transform.scale.y,transform.translation}]]` | `1.5` | `["0.4999499999999999","0.49995","1.0000499999999999","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/6B05DE14-37DB-4505-B242-8996669A30BD/6B05DE14-37DB-4505-B242-8996669A30BD.json#/events/1/effects/0` |
| `transition / apple:magic-move-implied-motion-path` | 1 | `N[N[N{group,zPosition}[T{group,hidden,opacity}]],N{group,zPosition}[T{group,hidden,opacity}]]` | `1.5` | `["0.0015000000000000568","1.5"]` | `["\"<absent>\"","\"EaseInEaseOut\""]` | `["\"both\"","\"forwards\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/271371F9-08BC-4095-A016-B35F3831D11C/271371F9-08BC-4095-A016-B35F3831D11C.json#/events/1/effects/0` |
| `transition / apple:wipe-iris` | 1 | `N[N[T,T{opacity}]]` | `3` | `["3"]` | `["\"EaseInEaseOut\""]` | `["\"both\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/A64827D1-ED43-4C67-AC71-09519705A351/A64827D1-ED43-4C67-AC71-09519705A351.json#/events/0/effects/0` |
| `transition / com.apple.iWork.Keynote.BUKFlop` | 1 | `N[N[T,T{opacity}]]` | `1` | `["1"]` | `["\"EaseInEaseOut\""]` | `["\"both\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/E13360EE-6DBD-4B04-A4AF-89AD3B698B47/E13360EE-6DBD-4B04-A4AF-89AD3B698B47.json#/events/0/effects/0` |
| `transition / com.apple.iWork.Keynote.BUKTwist` | 1 | `N[N[T,T{opacity}]]` | `1.5` | `["1.5"]` | `["\"EaseInEaseOut\""]` | `["\"both\""]` | `/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/F2-html/assets/C43E1B10-D7D7-462C-BC2A-E458C360EE17/C43E1B10-D7D7-462C-BC2A-E458C360EE17.json#/events/0/effects/0` |
