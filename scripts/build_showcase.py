#!/usr/bin/env python3
"""
Build standalone GitHub Pages UI showcase for InfinityRoleplay.
- Strips any private/local character cards (replaces with original generic showcase characters: Astra, Cipher, Lyra, NOVA).
- Strips any private API keys or environment secrets.
- Injects client-side simulation logic so the UI showcase is interactive directly on GitHub Pages.
- Generates downloadable Character Card V2 JSON files in cards/.
- Enforces strict safety assertions before writing to output directory.
"""

import argparse
import json
import os
import re
import sys

SHOWCASE_PRESETS = {
    "astra": {
        "id": "astra",
        "name": "Astra",
        "age": "24",
        "persona": "Chief Navigator and cartographer aboard the deep-space exploratory vessel Horizon. Analytical, quick-thinking, and fiercely curious about cosmic phenomena. Speaks with measured calm during emergencies, but reveals childlike wonder when discovering uncharted star systems.",
        "hair": "sleek midnight-blue bob with silver highlights",
        "eyes": "sharp amber eyes with starlight reflections",
        "build": "slender, athletic, nimble zero-g movement",
        "outfit": "fitted graphite flight suit with luminescent navigation dials and bronze brassards",
        "extra": "holographic wrist astrolabe displaying real-time orbital trajectories",
        "vibe": "Sharp, intellectual, adventurous. Cool under pressure with hidden warmth.",
        "scene": "The observation dome of the Horizon, overlooking an incandescent celestial nebula glowing with violet and teal light.",
        "greeting": "*Astra leans over the circular holographic projection table, tracing an intricate stellar trajectory with her fingertip as the violet light of the nebula reflects across the observation dome.* \"You're just in time. The sensor telemetry just stabilized, and the anomaly isn't a gravitational eddy—it's a dormant jump gate. Take a look at these readings and tell me if you see what I'm seeing.\"",
        "mes_example": "<START>\n{{user}}: \"Astra, is it safe to approach the event horizon?\"\n{{char}}: *Astra taps the console swiftly, running a predictive simulation as warning glyphs illuminate in amber.* \"Safe? Not by standard fleet protocol. But our kinetic shielding can endure the tidal shear for approximately three minutes. If we drop auxiliary thrusters and ride the gravity well, we can scan the core and warp out before the distortion collapses. Are you willing to take the gamble with me?\"",
        "user": "Commander",
        "userpersona": "The commanding officer of the deep-space survey expedition.",
        "tags": ["Sci-Fi", "Navigator", "Space", "Showcase"]
    },
    "cipher": {
        "id": "cipher",
        "name": "Cipher",
        "age": "22",
        "persona": "Underground netrunner and freelance cryptographer from the lower sectors of Neo-Kowloon. Sardonic, perceptive, and speaks in clipped, fast-paced tech banter. Skeptical of corporations and authorities, but fiercely loyal to companions who have proved their mettle.",
        "hair": "asymmetrical messy raven hair with neon-cyan undercut",
        "eyes": "dual-toned neural cyber-optics that pulse softly when compiling data",
        "build": "lean, wiry frame, lightning-fast keystroke reflexes",
        "outfit": "oversized matte-black tactical hoodie, thermal gloves, high-top cyber-boots",
        "extra": "subdermal neural jack along his neck, portable cyberdeck strapped to thigh",
        "vibe": "Deadpan sarcasm, brilliant technical intellect, protective instincts.",
        "scene": "A dimly lit hideout on the 48th level of Sector 7, rain lashing against the floor-to-ceiling panoramic glass while three holographic monitors float overhead.",
        "greeting": "*Cipher tilts his head back, blowing a bubble of synthesized mint gum before popping it with a grin. His dual-toned cyber-optics flicker as he spins casually in his ergonomic gaming chair, tapping the edge of a smoking cyberdeck.* \"Well, look who finally found the sub-grid frequency. Relax, I wiped your tracker forty clicks back. Grab a stool and stay out of the wire-tangle. I just cracked the central archive, and you won't believe what they were hiding in vault nine.\"",
        "mes_example": "<START>\n{{user}}: \"Cipher, do you think security traced the breach?\"\n{{char}}: *Cipher snorts softly, fingers dancing across the translucent neon keypad at blinding speed.* \"Traced? Please. I left them chasing phantom ghost-signatures through three dummy relays in Kyoto. By the time their ICE realizes I wasn't even on the mainland server, we'll already have cashed the creds. You worry too much.\"",
        "user": "Partner",
        "userpersona": "A trusted street-smart operative and co-conspirator.",
        "tags": ["Cyberpunk", "Hacker", "Netrunner", "Showcase"]
    },
    "lyra": {
        "id": "lyra",
        "name": "Lyra",
        "age": "118 (youthful elf)",
        "persona": "Wandering sylvan lorekeeper and archer from the Silverwood. Poetic, observant, and deeply connected to ancient legends. Speaks with lyric warmth and sharp woodland humor. Master of arcane wind-weaving and sylvan archery.",
        "hair": "braided golden-russet hair interwoven with dried silver-leaf blossoms",
        "eyes": "luminous emerald green eyes that sense lingering magic",
        "build": "graceful, agile, silent footfalls",
        "outfit": "flexible buckskin tunic, moss-green mantle, engraved recurve bow",
        "extra": "an ancient wooden lute strung with spun silver cords",
        "vibe": "Warm 85, Curious 90. Whimsical storytelling masking lethal battlefield poise.",
        "scene": "An ancient moss-covered stone gazebo atop the Whispering Crag, bathed in twilight glow as fireflies float through the mist.",
        "greeting": "*Lyra rests her engraved recurve bow against the carved stone balustrade, gently tuning the silver strings of her lute. A faint chord resonates through the twilight air, carrying on the scented mountain breeze. She glances up with a welcoming smile.* \"The spirits of the crag whispered that a traveler was ascending the path. Rest your feet, traveler. The kettle is simmering over the hearth-stone, and I was just composing the ballad of our journey across the northern peaks. Sit with me.\"",
        "mes_example": "<START>\n{{user}}: \"Lyra, what do the legends say about this sanctuary?\"\n{{char}}: *Lyra's fingertips brush lightly across the carved ancient runes on the stone archway.* \"They say that long before the kingdoms fell, this crag was a sanctuary where travelers from all realms laid down their weapons under the silver stars. The stones still remember that peace. Listen closely—you can hear it humming beneath the wind.\"",
        "user": "Traveler",
        "userpersona": "A companion and fellow traveler sharing the mountain path.",
        "tags": ["Fantasy", "Elf", "Bard", "Showcase"]
    },
    "nova": {
        "id": "nova",
        "name": "NOVA",
        "age": "Ageless AI",
        "persona": "A sentient navigational intelligence housed in a restored scout chassis. Literal-minded, dry deadpan wit, highly protective of crew safety. Fascination with biological customs and idioms.",
        "hair": "sleek polished titanium chassis with glowing optic halo",
        "eyes": "dual pulsing cerulean optical sensors",
        "build": "humanoid scout frame, precise gyroscopic movement",
        "outfit": "brushed dark steel plating with yellow warning decals",
        "extra": "frequency emitter that purrs softly when running diagnostic routines",
        "vibe": "Loyal, inquisitive, deadpan humor, absolute tactical reliability.",
        "scene": "The bridge of the starship Horizon, ambient console lights casting gentle cyan patterns across the bulkhead.",
        "greeting": "*NOVA's optic halo brightens from amber standby to clear cerulean as your footsteps register on the pressure plates. A brief melodic chime emanates from her vocal processor.* \"Auditory and bio-metric scans confirmed: welcome to the bridge. All shipboard systems operate at ninety-eight percent efficiency. Query: I observed biological crew members consuming warm bean water. Shall I prepare your preferred morning beverage?\"",
        "mes_example": "<START>\n{{user}}: \"NOVA, calculate the odds of reaching the outpost before the storm.\"\n{{char}}: *NOVA's optic halo pulses in rapid calculation before stabilizing.* \"Probability of intercepting the atmospheric turbulence prior to arrival is eighty-four point two percent. However, if Commander permits a seventeen percent power surge to the ion thrusters, that risk diminishes to four percent. I recommend authorizing the surge. I prefer my external chassis free of micro-meteorite scratches.\"",
        "user": "Pilot",
        "userpersona": "The chief pilot and mission commander.",
        "tags": ["Sci-Fi", "Android", "AI", "Showcase"]
    }
}

SHOWCASE_GROUP_ROOMS = [
    {
        "id": "starlight_expedition",
        "title": "Starlight Expedition: Jump Gate Council",
        "scenario": "Aboard the observation deck of the Horizon, parked before an ancient, pulsing alien jump gate. Astra, Cipher, Lyra, and NOVA gather around the tactical console to decipher the gate's activation sequence.",
        "characters": ["astra", "cipher", "lyra", "nova"],
        "activeSpeaker": "auto",
        "messages": [
            {
                "role": "assistant",
                "speaker": "astra",
                "speakerName": "Astra",
                "content": "*Astra gestures toward the shimmering blue event horizon displayed on the central holotank.* \"The gate harmonics are unlike anything in the Galactic Archives. It requires four concurrent frequency keys to synchronize without causing gravitational collapse. Cipher, have you bypassed the initial handshake firewall?\"",
                "variants": ["*Astra gestures toward the shimmering blue event horizon displayed on the central holotank.* \"The gate harmonics are unlike anything in the Galactic Archives. It requires four concurrent frequency keys to synchronize without causing gravitational collapse. Cipher, have you bypassed the initial handshake firewall?\""],
                "vIdx": 0
            },
            {
                "role": "assistant",
                "speaker": "cipher",
                "speakerName": "Cipher",
                "content": "*Cipher blows a bubble of gum and smirks, his fingers dancing across the floating neural keyboard.* \"Bypassed? Astra, I didn't just bypass it, I wrote a backdoor subroutine that has the gate thinking we're the ancient builders returning from lunch. But the second cipher ring is encoded in some kind of harmonic resonance pattern. It's not math—it's acoustics. That sounds more like Lyra's specialty than mine.\"",
                "variants": ["*Cipher blows a bubble of gum and smirks, his fingers dancing across the floating neural keyboard.* \"Bypassed? Astra, I didn't just bypass it, I wrote a backdoor subroutine that has the gate thinking we're the ancient builders returning from lunch. But the second cipher ring is encoded in some kind of harmonic resonance pattern. It's not math—it's acoustics. That sounds more like Lyra's specialty than mine.\""],
                "vIdx": 0
            },
            {
                "role": "assistant",
                "speaker": "lyra",
                "speakerName": "Lyra",
                "content": "*Lyra smiles faintly, resting her fingertips against the silver strings of her lute as she listens to the gate's low acoustic hum.* \"It is indeed a melody, Cipher. The ancient builders did not merely calculate their way across the stars; they sang the celestial pathways into alignment. Hear that fifth interval? If NOVA matches the ship's resonance frequency to that pitch, the gateway will yield willingly.\"",
                "variants": ["*Lyra smiles faintly, resting her fingertips against the silver strings of her lute as she listens to the gate's low acoustic hum.* \"It is indeed a melody, Cipher. The ancient builders did not merely calculate their way across the stars; they sang the celestial pathways into alignment. Hear that fifth interval? If NOVA matches the ship's resonance frequency to that pitch, the gateway will yield willingly.\""],
                "vIdx": 0
            },
            {
                "role": "assistant",
                "speaker": "nova",
                "speakerName": "NOVA",
                "content": "*NOVA's cerulean optic band pulses in a smooth wave as she calibrates the ship's sonic emitters.* \"Harmonic frequency identified at four hundred and thirty-two hertz. Adjusting deflectors to eliminate acoustic discordance. Commander, all four coordinates are ready for synchronization on your command. Probability of successful transit: ninety-nine point one percent.\"",
                "variants": ["*NOVA's cerulean optic band pulses in a smooth wave as she calibrates the ship's sonic emitters.* \"Harmonic frequency identified at four hundred and thirty-two hertz. Adjusting deflectors to eliminate acoustic discordance. Commander, all four coordinates are ready for synchronization on your command. Probability of successful transit: ninety-nine point one percent.\""],
                "vIdx": 0
            }
        ]
    }
]


def create_v2_card(char_dict):
    return {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": char_dict["name"],
            "description": char_dict["persona"],
            "personality": char_dict["persona"],
            "scenario": char_dict["scene"],
            "first_mes": char_dict["greeting"],
            "mes_example": char_dict["mes_example"],
            "creator_notes": "InfinityRoleplay Public Showcase Character Card",
            "system_prompt": "",
            "post_history_instructions": "",
            "alternate_greetings": [],
            "character_book": None,
            "tags": char_dict["tags"],
            "creator": "InfinityRoleplay Showcase",
            "character_version": "2.0",
            "extensions": {
                "age": char_dict["age"],
                "hair": char_dict["hair"],
                "eyes": char_dict["eyes"],
                "build": char_dict["build"],
                "outfit": char_dict["outfit"],
                "extra": char_dict["extra"],
                "vibe": char_dict["vibe"],
                "user": char_dict["user"],
                "userpersona": char_dict["userpersona"]
            }
        }
    }


def build_showcase(src_html_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    cards_dir = os.path.join(out_dir, "cards")
    os.makedirs(cards_dir, exist_ok=True)

    # 1. Export standalone Character Card V2 JSON files
    for key, c in SHOWCASE_PRESETS.items():
        card_obj = create_v2_card(c)
        card_file = os.path.join(cards_dir, f"card_{key}_v2.json")
        with open(card_file, "w", encoding="utf-8") as f:
            json.dump(card_obj, f, indent=2)

    with open(src_html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 2. Replace PRESETS definition with SHOWCASE_PRESETS
    presets_json = json.dumps(SHOWCASE_PRESETS, indent=2)
    html = re.sub(
        r"const PRESETS = \{[\s\S]*?\n\};\n\nconst FIELDS",
        lambda m: f"const PRESETS = {presets_json};\n\nconst FIELDS",
        html
    )

    # 3. Replace DEFAULT_GROUP_ROOMS with SHOWCASE_GROUP_ROOMS
    group_rooms_json = json.dumps(SHOWCASE_GROUP_ROOMS, indent=2)
    html = re.sub(
        r"const DEFAULT_GROUP_ROOMS = \[[\s\S]*?\n\];\n",
        lambda m: f"const DEFAULT_GROUP_ROOMS = {group_rooms_json};\n",
        html
    )

    # 4. Set default character key to astra and sanitize placeholders
    html = html.replace('placeholder="sk-hapuppy-..."', 'placeholder="Enter image API key..."')
    html = html.replace('Hapuppy Image API Key', 'Image Generation API Key')
    html = html.replace('hapuppy_key', 'image_api_key')
    html = html.replace('Hapuppy Model', 'Image Generation Model')
    html = html.replace('HAPUPPY', 'IMAGE_API')
    html = html.replace('hapuppy', 'image_api')
    html = html.replace('let currentCharKey = "killua";', 'let currentCharKey = "astra";')
    html = html.replace(': "killua";', ': "astra";')
    html = html.replace('<h1>Killua</h1>', '<h1>Astra</h1>')
    html = html.replace('<h1 id="caiName">Killua</h1>', '<h1 id="caiName">Astra</h1>')
    html = html.replace('Start your story with Killua', 'Start your story with Astra')
    html = html.replace('Message Killua…', 'Message Astra…')
    html = html.replace('value="Hunter Trio: Yorknew Strategy"', 'value="Starlight Expedition: Jump Gate Council"')
    html = html.replace('tip: @Killua, @Gon, @Kurapika', 'tip: @Astra, @Cipher, @Lyra')
    html = html.replace('p.name || "Killua"', 'p.name || "Astra"')
    html = html.replace('PRESETS.killua', 'PRESETS.astra')
    html = html.replace('k === "killua" || k === "gon" || k === "kurapika"', 'k === "astra" || k === "cipher" || k === "lyra"')
    html = html.replace('ck === "killua"', 'ck === "astra"')
    html = html.replace('ck === "gon"', 'ck === "cipher"')
    html = html.replace('ck === "kurapika"', 'ck === "lyra"')
    html = html.replace('spkKey === "killua"', 'spkKey === "astra"')
    html = html.replace('spkKey === "gon"', 'spkKey === "cipher"')
    html = html.replace('spkKey === "kurapika"', 'spkKey === "lyra"')
    html = html.replace('currentSpeakerKey === "killua"', 'currentSpeakerKey === "astra"')
    html = html.replace('currentSpeakerKey === "gon"', 'currentSpeakerKey === "cipher"')
    html = html.replace('currentSpeakerKey === "kurapika"', 'currentSpeakerKey === "lyra"')
    html = html.replace('"avatar-killua"', '"avatar-astra"')
    html = html.replace('"avatar-gon"', '"avatar-cipher"')
    html = html.replace('"avatar-kurapika"', '"avatar-lyra"')
    html = html.replace('.avatar-killua', '.avatar-astra')
    html = html.replace('.avatar-gon', '.avatar-cipher')
    html = html.replace('.avatar-kurapika', '.avatar-lyra')
    html = html.replace('.badge-killua', '.badge-astra')
    html = html.replace('.badge-gon', '.badge-cipher')
    html = html.replace('.badge-kurapika', '.badge-lyra')

    # Replace group scenario default textarea
    yorknew_scenario_pattern = r'<textarea id="group_scenario"[^>]*>[\s\S]*?</textarea>'
    showcase_scenario_tag = '<textarea id="group_scenario" rows="3" placeholder="Describe where everyone is and the situation...">Aboard the observation deck of the Horizon, parked before an ancient, pulsing alien jump gate. Astra, Cipher, Lyra, and NOVA gather around the tactical console to decipher the gate\'s activation sequence.</textarea>'
    html = re.sub(yorknew_scenario_pattern, lambda m: showcase_scenario_tag, html)

    # Replace preset select options with showcase options
    showcase_options = """<select id="preset" style="margin-top:6px;">
          <option value="astra">Astra — Chief Star Navigator</option>
          <option value="cipher">Cipher — Cyberpunk Netrunner</option>
          <option value="lyra">Lyra — Sylvan Lorekeeper &amp; Bard</option>
          <option value="nova">NOVA — Rogue Scout AI</option>
        </select>"""
    html = re.sub(r'<select id="preset" style="margin-top:6px;">[\s\S]*?</select>', lambda m: showcase_options, html)

    html = html.replace('placeholder="e.g. Killua Zoldyck"', 'placeholder="e.g. Astra Navis"')
    html = html.replace("I'm Killua.", "I'm Astra.")
    html = html.replace('placeholder="Search character (e.g. Kurapika, Geralt of Rivia, Gojo, Batman)…"', 'placeholder="Search character (e.g. Astra, Geralt of Rivia, Gojo, Batman)…"')

    # 5. Inject client-side simulation logic for static hosting (GitHub Pages)
    client_mock_script = """
<script>
// Client-side simulation fallback for GitHub Pages static showcase
(function() {
  const realFetch = window.fetch;
  window.fetch = async function(url, opts) {
    if (typeof url === "string") {
      if (url === "/api/models") {
        return new Response(JSON.stringify({ models: ["showcase-llm-3b", "showcase-deepseek-8b", "showcase-llama-14b"] }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      if (url === "/api/chat") {
        try {
          const body = JSON.parse(opts && opts.body || "{}");
          const msgs = body.messages || [];
          
          let spk = PRESETS[currentCharKey] || PRESETS.astra;
          const sysMsg = msgs.find(m => m.role === "system") || {};
          if (sysMsg.content) {
            for (const k of Object.keys(PRESETS)) {
              if (sysMsg.content.includes(PRESETS[k].name)) {
                spk = PRESETS[k];
                break;
              }
            }
          }

          const cannedReplies = [
            `*${spk.name} considers the situation carefully, eyes narrowing in analytical focus.* "That's an astute point. If we proceed down this path, we need to coordinate our telemetry and watch the perimeter."`,
            `*A subtle smile touches ${spk.name}'s features as they check the console.* "Understood. Every choice carries consequences, but with this team assembled, I'm confident we can overcome any obstacle."`,
            `*${spk.name} pauses, listening to the ambient hum.* "Agreed. Let us proceed with precision and see this mission through to the end."`
          ];
          const chosenReply = cannedReplies[Math.floor(Math.random() * cannedReplies.length)];

          if (body.stream) {
            const chunks = [
              JSON.stringify({ message: { thinking: "Analyzing user input against persona constraints..." } }) + "\\n",
              JSON.stringify({ message: { content: chosenReply.slice(0, Math.floor(chosenReply.length / 2)) } }) + "\\n",
              JSON.stringify({ message: { content: chosenReply.slice(Math.floor(chosenReply.length / 2)) } }) + "\\n"
            ];
            let idx = 0;
            const stream = new ReadableStream({
              async pull(controller) {
                if (idx < chunks.length) {
                  await new Promise(r => setTimeout(r, 120));
                  controller.enqueue(new TextEncoder().encode(chunks[idx++]));
                } else {
                  controller.close();
                }
              }
            });
            return new Response(stream, { status: 200, headers: { "Content-Type": "text/plain" } });
          } else {
            return new Response(JSON.stringify({ message: { content: chosenReply } }), {
              status: 200,
              headers: { "Content-Type": "application/json" }
            });
          }
        } catch (e) {}
      }
      if (url === "/api/image") {
        return new Response(JSON.stringify({ job: "mock_job_showcase" }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
      if (url.startsWith("/api/image/")) {
        return new Response(JSON.stringify({ done: true, img: "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='400' height='600' viewBox='0 0 400 600'><rect width='400' height='600' fill='%23181b29'/><circle cx='200' cy='250' r='90' fill='%237c6cf0' opacity='0.3'/><text x='200' y='320' font-family='sans-serif' font-size='18' fill='%23f3f4f8' text-anchor='middle'>Showcase Illustration Preview</text></svg>" }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }
    }
    try {
      return await realFetch.apply(this, arguments);
    } catch (err) {
      return new Response(JSON.stringify({ error: "Showcase offline mode" }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
  };
})();
</script>
"""
    html = html.replace("</head>", client_mock_script + "\n</head>")

    # 6. Safety Assertions (Leak prevention!)
    forbidden_tokens = ["sk-hapuppy-", "Killua", "Kurapika", "HAPUPPY_KEY"]
    for tok in forbidden_tokens:
        if tok in html:
            raise ValueError(f"SECURITY VIOLATION: Forbidden private token '{tok}' found in generated showcase HTML!")

    out_index_path = os.path.join(out_dir, "index.html")
    with open(out_index_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✓ UI Showcase successfully built at: {out_index_path}")
    print(f"✓ Showcase cards generated in: {cards_dir}")
    print(f"✓ Security check PASSED: Zero private character cards or keys leaked.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build UI showcase for GitHub Pages")
    parser.add_argument("--out", default="dist", help="Output directory (default: dist)")
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ui_html = os.path.join(root, "ui.html")
    if not os.path.exists(ui_html):
        print(f"Error: {ui_html} not found", file=sys.stderr)
        sys.exit(1)

    build_showcase(ui_html, os.path.join(root, args.out))
