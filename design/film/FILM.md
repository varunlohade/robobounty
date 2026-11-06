# Three centimetres

Current direction: **a flat tracked vacuum window cleaner**, inspired by the real home-window-cleaning family, in a fictional high-rise failure scenario. This document supersedes both the articulated vacuum walker and the cradle-mounted arm. No arms, legs, suction cups on limbs, cradle, catch tray or hall of physical test walls appears in the current film.

## Deliverables and status

A 45-second film treatment, a separate five-second hero loop prompt, and six newly generated key stills in `keyframes/shot-1.png` through `shot-6.png`. Exactly **six image generations** were used for this direction, with no retries. Shot 1 establishes the appearance; every later image uses it as its sole image reference. The attached cradle photo was inspected as context but was not used as an image-generation reference. Built-in imagegen was used; exact still prompts are in `keyframes/PROMPTS.md`.

These are AI-generated visual concepts, not photographs of an operating prototype, calculated simulation outputs or finished video. No real video-generation tool is available here. No video service, purchase, signup, publishing or hosting was used. The six PNGs are delivery-conformed to 2048 × 1152, exact 16:9. Technical resizing does not correct generated mechanical geometry.

## What the evidence supports

Read the updated local research note: `../../docs/research/facade-robots.md`. Its owner-correction section supersedes its earlier cradle reference for this task.

The real design family exists. HOBOT documents a square vacuum body, two caterpillar treads, cleaning cloth and safety rope. Its manual also says not to use the device on rainy or humid days. That supports our choice of basic mechanism and makes the rain scene an adverse-condition concept, not a recommended use. [Manufacturer product description](https://mail.hobot.com.tw/WEB/Products_list_Window_Robot_268.php), [manufacturer manual](https://mail.hobot.com.tw/app_document/HOBOT288UM_EN.pdf).

ECOVACS documents slipping tracks, insufficient air pressure at gaps/cracks, and obstacle interference. Those are real failure categories; the exact proposed mullion sequence below remains an engineering hypothesis for this fictional geometry. [Manufacturer troubleshooting manual](https://site-static.ecovacs.com/upload/file/support/2025/12/16/081350_7068%24WINBOTW3OMNIInstructionManualEU.pdf).

No evidence reviewed validates a home cleaner for a rainy 45-storey exterior, a roof-length tether, or this film's exact arrest distance. Do not transfer the research note's 45-storey cradle deployment to this machine. No product's exact industrial design, performance figures, weather rating or certification is claimed. A real deployment would require a validated whole system, including weather protection, power, attachment, sensing and tether/anchor dynamics.

## Canonical robot and setting

One original unbranded window-cleaning robot: a low flat 35 cm square white shell with softly rounded corners, a recessed broad light-grey rectangular top panel, a narrow dark-grey perimeter bumper, no handle or decorative lights; one continuous flexible vacuum skirt against the glass, two short parallel black rubber drive tracks recessed on the glass-facing underside, and pale-grey microfiber cleaning pads around its underside edge. A single thin grey safety tether attaches at the centre of its upper edge and runs upward toward a roof anchor. No arms, legs, projecting suction cups, cradle or external squeegee bar.

Repeat that description in each generation prompt. Nominal 35 cm width is an art-direction dimension, not a specification taken from a real product. The top panel is a plain shallow inset, not a screen. Tracks and sealed suction area are on the underside: no tank tracks attached to the exposed shell. The perimeter cloth wipes a dirt film but does not erase rain or glass reflections. No external brush arm or squeegee bar.

An invented tower taller than the working floor puts the robot near the 45th storey, with the roof anchor above and relatively nearby; do not confuse height above ground with tether length. One thin line runs upward to that off-screen roof anchor. A short onboard-powered shot is assumed; battery endurance and weather sealing are unvalidated. Do not add a second power lead or pretend the depicted consumer-sized package is production-qualified.

Overcast daylight, neutral silver/white/grey, light wind-driven rain, visible glass and aluminium mullions. Entirely fictional skyline. No text, labels, logos, real recognizable buildings, brands or people's faces; no people in frame. No orange/teal grade. Shots 1–4 and 6 are photoreal; shot 5 is explicitly a digital visualization.

## Physics contract

1. **Adhesion is not vertical lift.** Approximate normal attraction is `N_vac = Δp × A_effective`. Vertical support comes from track/pad friction and, after arrest, the tether. A simplified friction bound is `F_t ≤ μ N_contact`; gravity is `mg`. Actual load sharing, wiping drag, wind loads, peel moments and nonuniform pressure matter. Comparing suction force directly with weight is insufficient.
2. **Failure trigger:** the robot drives into a mullion because its edge detection or stopping response fails in this scenario. A small bevel permits slight leading-edge lift before the body stops; the seal leaks and pressure differential drops faster than the fan can recover. A tall square frame simply blocking the bumper would not automatically cause seal loss. The geometry must show the small lift, not assume it.
3. **Wet contact:** a water/soil film can reduce usable traction, but no universal wet-glass coefficient is claimed. Wind supplies disturbance and can add peel load; it is not a magic suction-off switch. Do not use gondola pendulum physics for this flush-to-glass robot.
4. **Slip:** with insufficient available upward friction, the body translates down the pane a few centimetres. Some skirt/pad/track contact remains. This is not a robot flying away or tumbling into space.
5. **Arrest:** the line starts with centimetres of available slack, not metres. A total slip of roughly 3 cm is an animation target conditional on slack, rope extension, anchor compliance, residual friction and mass. An illustrative allocation is 2 cm slack take-up plus 1 cm deceleration travel; it is not a tested rope property. A roof line with excessive stretch would invalidate this depiction. The tether attaches to a load-bearing point at the upper centre and stays close to the glass plane to limit peel torque. Tension must build over finite time; do not animate an infinitely rigid stop. The anchor and line must take dynamic load, not merely static weight. Neither is sized or certified by this film.
6. **After arrest:** tracks stop, line holds and the robot stays near the pane. Do not invent self-recovery, mullion traversal, a retracting winch or restored suction. The film ends in a held fault state.

Illustrative plausibility check only: assume `m = 2 kg`, `A = 0.04 m²`, `μ = 0.25` and initial `Δp = 2800 Pa`. Then normal vacuum force is 112 N and the simple friction ceiling is 28 N, above the 19.6 N weight before cleaning drag and wind are included. At an assumed leaked `Δp = 600 Pa`, that ceiling becomes 6 N, below weight, so slipping is possible. **Every input here is an assumed scenario value, not a measurement of our fictional robot or a safety margin.** The check explains the causal direction only; it is not a coupled seal/flow/contact/tether simulation.

## 45-second edit and standalone video prompts

16:9, 24 fps; 45 seconds equals 1,080 frames. The keyframes illustrate moments; they do not establish temporal physics or a measured slip distance. Use shot 1 for appearance continuity, but obey the mechanical constraints below over any generated visual anomaly.

### Shot 1 — One clean path | 00:00–00:07 (7 seconds)

Keyframe: [shot-1.png](keyframes/shot-1.png). Camera: 70 mm, shallow exterior three-quarter angle.

**Ready-to-use video prompt**

> Generate a 7-second shot at 24 fps, 16:9. One original unbranded window-cleaning robot: a low flat 35 cm square white shell with softly rounded corners, a recessed broad light-grey rectangular top panel, a narrow dark-grey perimeter bumper, no handle or decorative lights; one continuous flexible vacuum skirt against the glass, two short parallel black rubber drive tracks recessed on the glass-facing underside, and pale-grey microfiber cleaning pads around its underside edge. A single thin grey safety tether attaches at the centre of its upper edge and runs upward toward a roof anchor. No arms, legs, projecting suction cups, cradle or external squeegee bar. The robot advances upward slowly within one wet pane. Its two underside rubber tracks roll against glass and perimeter pads wipe a 35 cm lane in the dirt film, leaving residual beads rather than removing the glass reflection. Start about 20 cm below a horizontal mullion and finish closer to it. Keep the shell flat to glass and the tether nearly straight with only centimetres of available slack. Camera makes a gentle lateral move; no camera orbit revealing an invented underside. Camera: 70 mm, shallow exterior three-quarter angle. Photoreal neutral overcast light, light rain, modest wind, silver curtain-wall glass and anonymous city at about 45-storey height. Preserve the same square white-grey robot, its continuous skirt, two underside tracks and single upper-centre roof tether. No arms, legs, projecting suction pads, cradle, trays, physical test-wall hall, impossible wall crossing, large fall or invented machinery. No text, logos, watermarks, brands, real identifiable buildings, people or faces. No shape changes or extra tethers.

**Sound and purpose:** Close fan hum and damp microfiber scrape. Establish ordinary work.

### Shot 2 — Forty-five storeys | 00:07–00:13 (6 seconds)

Keyframe: [shot-2.png](keyframes/shot-2.png). Camera: 24 mm, steep view downward along the facade.

**Ready-to-use video prompt**

> Generate a 6-second shot at 24 fps, 16:9. One original unbranded window-cleaning robot: a low flat 35 cm square white shell with softly rounded corners, a recessed broad light-grey rectangular top panel, a narrow dark-grey perimeter bumper, no handle or decorative lights; one continuous flexible vacuum skirt against the glass, two short parallel black rubber drive tracks recessed on the glass-facing underside, and pale-grey microfiber cleaning pads around its underside edge. A single thin grey safety tether attaches at the centre of its upper edge and runs upward toward a roof anchor. No arms, legs, projecting suction cups, cradle or external squeegee bar. Cut to the robot small on the right of a vast vertical curtain wall, anonymous city streets far below at left. It continues the same slow upward movement within the same pane. Roof anchor is above camera, off-screen; one tether extends upward out of frame. Modest wind inclines light rain and slightly deflects the unloaded tether; it does not throw the robot or move rigid mullions. Hold the camera almost still. Preserve a narrow clean path below it. Camera: 24 mm, steep view downward along the facade. Photoreal neutral overcast light, light rain, modest wind, silver curtain-wall glass and anonymous city at about 45-storey height. Preserve the same square white-grey robot, its continuous skirt, two underside tracks and single upper-centre roof tether. No arms, legs, projecting suction pads, cradle, trays, physical test-wall hall, impossible wall crossing, large fall or invented machinery. No text, logos, watermarks, brands, real identifiable buildings, people or faces. No shape changes or extra tethers.

**Sound and purpose:** Wind becomes audible; the fan stays steady. No people below are resolved.

### Shot 3 — The boundary | 00:13–00:20 (7 seconds)

Keyframe: [shot-3.png](keyframes/shot-3.png). Camera: 100 mm macro along the upper skirt and mullion.

**Ready-to-use video prompt**

> Generate a 7-second shot at 24 fps, 16:9. One original unbranded window-cleaning robot: a low flat 35 cm square white shell with softly rounded corners, a recessed broad light-grey rectangular top panel, a narrow dark-grey perimeter bumper, no handle or decorative lights; one continuous flexible vacuum skirt against the glass, two short parallel black rubber drive tracks recessed on the glass-facing underside, and pale-grey microfiber cleaning pads around its underside edge. A single thin grey safety tether attaches at the centre of its upper edge and runs upward toward a roof anchor. No arms, legs, projecting suction cups, cradle or external squeegee bar. The robot reaches a projecting horizontal aluminium mullion from below. Its upper bumper noses onto a small bevel and pitches the leading edge outward only millimetres; the lower contact remains on the pane. A tiny gap opens in the continuous vacuum skirt. Hold on the actual rubber-to-glass interface, not merely the shell seam. Show a brief track hesitation and the beginning of downward creep at the end. No crossing the mullion, levitation, explosion, visible vacuum plume or shattered glass. This is a deliberately failed edge-detection/stop case, not normal intended operation. Camera: 100 mm macro along the upper skirt and mullion. Photoreal neutral overcast light, light rain, modest wind, silver curtain-wall glass and anonymous city at about 45-storey height. Preserve the same square white-grey robot, its continuous skirt, two underside tracks and single upper-centre roof tether. No arms, legs, projecting suction pads, cradle, trays, physical test-wall hall, impossible wall crossing, large fall or invented machinery. No text, logos, watermarks, brands, real identifiable buildings, people or faces. No shape changes or extra tethers.

**Sound and purpose:** A small dull contact, air-leak hiss and changed fan timbre. No dramatic crash.

### Shot 4 — Three centimetres | 00:20–00:25 (5 seconds)

Keyframe: [shot-4.png](keyframes/shot-4.png). Camera: 85 mm, locked shallow side view including the whole body and frame.

**Ready-to-use video prompt**

> Generate a 5-second shot at 24 fps, 16:9. One original unbranded window-cleaning robot: a low flat 35 cm square white shell with softly rounded corners, a recessed broad light-grey rectangular top panel, a narrow dark-grey perimeter bumper, no handle or decorative lights; one continuous flexible vacuum skirt against the glass, two short parallel black rubber drive tracks recessed on the glass-facing underside, and pale-grey microfiber cleaning pads around its underside edge. A single thin grey safety tether attaches at the centre of its upper edge and runs upward toward a roof anchor. No arms, legs, projecting suction cups, cradle or external squeegee bar. Continue the same incident: reduced vacuum and wet contact allow a short downward slip along the pane, approximately three centimetres in total, not a free fall. The short available tether slack is taken up and the single roof-directed line becomes taut; small elastic compliance and residual glass contact decelerate the body. Keep it upright and nearly flush to glass, intact, just below the mullion. A short smear interrupts the clean path. Stop drive motion and hold. Do not cut from a large slack loop to a magically short arrest. Do not bounce, swing out, resume cleaning or claim automatic resealing. Camera: 85 mm, locked shallow side view including the whole body and frame. Photoreal neutral overcast light, light rain, modest wind, silver curtain-wall glass and anonymous city at about 45-storey height. Preserve the same square white-grey robot, its continuous skirt, two underside tracks and single upper-centre roof tether. No arms, legs, projecting suction pads, cradle, trays, physical test-wall hall, impossible wall crossing, large fall or invented machinery. No text, logos, watermarks, brands, real identifiable buildings, people or faces. No shape changes or extra tethers.

**Sound and purpose:** Short rubber squeak, subtle line loading, then a held fan note. The outcome is a stopped machine, not recovery.

### Shot 5 — Failures rehearsed, not hidden | 00:25–00:39 (14 seconds)

Keyframe: [shot-5.png](keyframes/shot-5.png). Camera: fixed orthographic three-quarter digital view.

**Ready-to-use video prompt**

> Generate a 14-second shot at 24 fps, 16:9. One original unbranded window-cleaning robot: a low flat 35 cm square white shell with softly rounded corners, a recessed broad light-grey rectangular top panel, a narrow dark-grey perimeter bumper, no handle or decorative lights; one continuous flexible vacuum skirt against the glass, two short parallel black rubber drive tracks recessed on the glass-facing underside, and pale-grey microfiber cleaning pads around its underside edge. A single thin grey safety tether attaches at the centre of its upper edge and runs upward toward a roof anchor. No arms, legs, projecting suction cups, cradle or external squeegee bar. Cut decisively from photography to an unmistakably computer-rendered scene: matte white-grey shell, simplified transparent glass, visible neutral mesh topology, no city, no room or physical test wall installation. Show four sequential full-screen runs of the SAME single pane and robot, with hard editorial resets, each about 3.5 seconds. Run A repeats the mullion seal leak and tether-arrested short slip. Run B varies approach angle slightly and leaves an uneven pad streak after seal loss. Run C begins with a thicker water film and shows track slip before reaching the frame, followed by a stop. Run D shows a candidate stop before the mullion with adhesion preserved; leave an uncleaned edge strip visible. Only change the stated variable between runs; geometry, gravity and roof-directed tether remain consistent. These are independent simulated scenarios, not four machines sharing a physical hall. A muted violet footprint may schematically mark contact beneath the skirt but is not a calibrated pressure plot. No numeric results or success claims. Tracks belong on the underside, with their rolling directions aligned for upward travel. Camera: fixed orthographic three-quarter digital view. Clearly digital neutral mesh visualization; do not make this look like filmed test equipment. Preserve the same square white-grey robot, its continuous skirt, two underside tracks and single upper-centre roof tether. No arms, legs, projecting suction pads, cradle, trays, physical test-wall hall, impossible wall crossing, large fall or invented machinery. No text, logos, watermarks, brands, real identifiable buildings, people or faces. No shape changes or extra tethers.

**Sound and purpose:** Dry simulation room tone and four restrained reset ticks. Optional off-screen voice: 'First, meet the failure in simulation.' No words in frame.

### Shot 6 — Held | 00:39–00:45 (6 seconds)

Keyframe: [shot-6.png](keyframes/shot-6.png). Camera: 50 mm, quiet wide exterior oblique composition.

**Ready-to-use video prompt**

> Generate a 6-second shot at 24 fps, 16:9. One original unbranded window-cleaning robot: a low flat 35 cm square white shell with softly rounded corners, a recessed broad light-grey rectangular top panel, a narrow dark-grey perimeter bumper, no handle or decorative lights; one continuous flexible vacuum skirt against the glass, two short parallel black rubber drive tracks recessed on the glass-facing underside, and pale-grey microfiber cleaning pads around its underside edge. A single thin grey safety tether attaches at the centre of its upper edge and runs upward toward a roof anchor. No arms, legs, projecting suction cups, cradle or external squeegee bar. Hard cut back to the photoreal stopped machine at approximately the 45th storey, matching the post-slip position of shot 4. It remains near-flush to the pane, three centimetres below the mullion, supported by the single taut roof-directed tether. Leave the interrupted cleaning lane and short smear visible. Keep the robot on the right third and pale reflected sky on the left. Light rain and modest wind continue. No renewed cleaning, rescue, retrieval, instant fix, full fall or victory indicator. Finish on a restrained hold. Camera: 50 mm, quiet wide exterior oblique composition. Photoreal neutral overcast light, light rain, modest wind, silver curtain-wall glass and anonymous city at about 45-storey height. Preserve the same square white-grey robot, its continuous skirt, two underside tracks and single upper-centre roof tether. No arms, legs, projecting suction pads, cradle, trays, physical test-wall hall, impossible wall crossing, large fall or invented machinery. No text, logos, watermarks, brands, real identifiable buildings, people or faces. No shape changes or extra tethers.

**Sound and purpose:** Wind persists; no triumphant resolution. Failure is contained, with recovery left to an authorized process outside this film.

## Honest simulated test worlds

Shot 5's four successive runs are separate simulated conditions, not physical rooms or holographic objects. A hard reset between runs signals an independent test; geometry must not morph mid-run. These are **proposed** tests, not trials already executed by us. Show failures as well as the candidate stop, retaining its uncleaned strip. The contact tint is schematic, not an actual pressure result or validation metric. Do not imply that one successful digital run proves real-world readiness.

A later real simulator would need rigid-body mass/inertia, track contact and friction calibration, seal leakage versus gap, fan pressure-flow response, sensor/stop latency, a projecting mullion mesh, wind loads and rope slack/stiffness/damping. Sweep these as documented assumptions until measurements replace them. Test arrest distance, peak tether force, peel angle, residual adhesion and missed cleaning area. No numerical test output is invented in the film.

## Five-second hero loop

Use shot 6 as the poster: the robot is held and stationary after the short slip, the clean lane and fault smear visible. The loop conveys the glass-cleaning task and height without repeatedly staging an accident. It does not depict successful continued operation in rain.

**Ready-to-use prompt**

> Create a five-second silent 16:9 loop at 24 fps. One original unbranded window-cleaning robot: a low flat 35 cm square white shell with softly rounded corners, a recessed broad light-grey rectangular top panel, a narrow dark-grey perimeter bumper, no handle or decorative lights; one continuous flexible vacuum skirt against the glass, two short parallel black rubber drive tracks recessed on the glass-facing underside, and pale-grey microfiber cleaning pads around its underside edge. A single thin grey safety tether attaches at the centre of its upper edge and runs upward toward a roof anchor. No arms, legs, projecting suction cups, cradle or external squeegee bar. Locked 50 mm exterior shallow-angle composition on fictional curtain-wall glass near the 45th storey, robot small on the right third, three centimetres below a horizontal mullion. Single upward roof tether taut, body held near-flush and stationary after a short slip, tracks stopped. Keep the interrupted clean path in the dirt film and small smear below it. Overcast sky reflected at left; neutral white and grey. Fine water beads remain stationary. Only a very subtle periodic change in sky reflection returns to its starting state. No new cleaning stroke, falling droplet, swinging, recovery, reversed slip or change in tether length. Match first and last pose, reflection and exposure. No text, logos, watermarks, brands, recognizable buildings, people or faces. No arms, legs, external pads or cradle.

Timing: 0–1 s hold, 1–4 s minute cyclic reflection shift, 4–5 s hold. Export 120 unique frames without a duplicated endpoint. Check the actual join before use; an image prompt cannot guarantee a seamless loop. A static poster is preferable to an unverified mechanical or looping artifact. No website or video file has been made.

## Keyframe inspection and remaining limitations

All six generated outputs were inspected. They consistently use the flat white/grey shell, edge cloth, glass setting and single roof-directed line; no arms or cradle remain. Shot 5 visibly changes to a digital mesh look. The keyframes are **concept art, not mechanically authoritative CAD**:

- In shots 1 and 4 a tread edge is more exposed than the intended recessed layout. Shot 5 represents the underside tracks as short exposed segments and does not reliably resolve their complete parallel belt paths. For animation/CAD, place both full belts on the glass-facing underside, aligned to produce the depicted upward travel; do not copy an ambiguous tread orientation from the still.
- Shot 3 shows a narrow dark contact region at the mullion, but a still cannot prove a millimetre-scale skirt gap or pressure loss. The video must resolve the rubber/glass separation and causal sequence.
- The shot-5 violet region is a stylized highlight, not a computed pressure map. Keep any actual contact visualization confined to the modeled underside; no quantitative inference can be made from this image.
- Clearance, 35 cm size, 45-storey height, rope strain and a 3 cm arrest are narrative targets, not measurable confirmations from the generated perspectives. Shot 6's cleaning path is subtler than shot 1's; maintain the same interrupted lane in motion.

The six-generation cap has been reached; no further image retries were made. Physics credibility in finished motion requires a dimensioned model and calibrated simulation, not merely image-to-video interpolation. Do not claim deployment readiness, actual tests passed, or a validated wet-weather operating limit.
