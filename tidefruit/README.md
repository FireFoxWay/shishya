# Tidefruit

A 2D, top-down, real-time multiplayer grind game in the style of the
fruit-and-seas Roblox games: level from **1 to 3,000** across **four seas**,
eat one of **27 fruits** with five skills each, hunt **34 bosses** and roaming
**sea beasts**, and fight other players for bounty.

It is an original game with its own names, art and numbers. It is not
affiliated with Roblox or any existing game.

```
node server.js          # then open http://localhost:3000
```

No `npm install`: the server is plain Node (22+), including its own
WebSocket implementation, and the client is plain canvas and DOM.

## Playing together

Everyone who opens the same server shares one world: they see each other move
and fight in real time, chat, steal kills off the same boss, and (with PvP on)
attack each other.

| where | how |
|---|---|
| on this machine | `node server.js`, open `http://localhost:3000` in two tabs |
| on your Wi-Fi | friends open `http://<your-LAN-IP>:3000` |
| on the internet | deploy it anywhere that runs a Node process and allows WebSockets (Render, Railway, Fly.io, a VPS). The start command is `npm start`; the port comes from `PORT` |

Saves live in `data/saves.json` (override with `SAVE_FILE=…`). On a host with an
ephemeral disk, point `SAVE_FILE` at a persistent volume or progress resets on
redeploy. The server writes the file every 30 seconds and on shutdown,
atomically (temp file, then rename).

A name is claimed by the first browser that uses it: the browser keeps a random
token in `localStorage`, and the server stores only its SHA-256.

## The game

**Progression.** Each island has a Quest Giver offering its two monsters and
its boss. Quests renew themselves when complete, so the loop is: pick the
highest quest you qualify for, grind it, move on. Each level gives 3 stat
points across Melee, Defense, Sword, Gun and Fruit (cap 3,000 each). A
simulated straight grind reaches level 700 in about 4 hours and 3,000 in about
16.

| sea | levels | islands | town |
|---|---|---|---|
| Dawn Sea | 1 – 700 | 10 | Driftwood Isle |
| Crimson Sea | 700 – 1,500 | 9 | Harbor of Embers |
| Tempest Sea | 1,500 – 2,300 | 8 | Port of Storms |
| Abyssal Sea | 2,300 – 3,000 | 7 | Lantern Reef |

The final boss, **The Abyssal Sovereign**, is level 3,000.

**Weapons.** Four slots: a fighting style (6), a sword (18), a gun (10) and a
fruit (27). Using a weapon raises its mastery (max 600), which unlocks its
skills: Z at 1, X at 25, C at 75, V at 150, F at 250. That is 209 skills in all,
built from twelve kinds: projectiles, bursts, strikes at the cursor, beams,
dashes, lingering fields, barrages, pulls, teleports, chain lightning, buffs
and transformations.

**Fruits** come in five rarities (Common → Mythical) and three types:
*Natural*, *Elemental* (phases through some monster hits; takes reduced PvP
damage from players without Aura), and *Beast* (V transforms you: +30% damage,
+20% speed, damage reduction, regeneration). You get them from the Fruit
Merchant (stock rotates every 15 minutes), the Fruit Mystic (a random roll every
20 minutes), boss drops, sea beasts, and the wild: one falls somewhere in each
sea every few minutes. Fruits can be stored (12 slots), eaten, dropped for
another player, and awakened with fragments (+25% damage, faster cooldowns).

**Towns** carry every shop: Blacksmith, Gunsmith, Martial Master, Fruit
Merchant, Fruit Mystic, Aura Sage (Aura, Flash Step, Instinct), Stat Trainer
(refund), Ferry Captain (sea travel) and, from the second sea, the Awakener.
Monsters will not follow anyone into a town or up to an NPC.

**PvP.** From level 20 you can switch PvP on. Towns are safe zones. Pirates can
attack anyone with PvP on; Marines cannot hurt Marines. A kill moves bounty
(Pirates) or honor (Marines) from the victim to the killer. There is a 10 second
lock on switching PvP off after a fight.

**Codes:** `FIRSTSAIL` (a random fruit), `SEAFRUIT` ($25,000), `TIDES2X`
(2× XP for 30 minutes), `FRESHSTART` (free stat reset). Each works once per
captain.

**Controls.** WASD to move, mouse to aim, hold left click to attack,
Z X C V F for skills, 1–4 to switch slots, Q or Space to dash, E to talk,
K for stats, I for the bag, M for the map, Tab for the leaderboard, Enter to chat.
Walking into the sea puts you in a boat. On a phone or tablet there is a
joystick, an attack button and tappable skills, and skills aim themselves at the
nearest enemy.

## How it holds together

```
server.js            HTTP for the client, WebSocket at /ws, 30 Hz game loop, autosave
server/ws.js         RFC 6455 WebSocket server (text frames, ping/pong, backpressure)
server/game.js       the authoritative world: players, mobs, bosses, skills, quests, shops, PvP
server/store.js      saves in one JSON file
shared/tf.js         rules and content both sides load: formulas, fruits, weapons,
                     seas, islands, and the island geometry that decides land from water
public/              the client: render.js (canvas), ui.js (HUD and menus), main.js (net, input)
test/sim.js          the real Game on a virtual clock: every skill, PvP, bosses, travel, shops
test/smoke.js        boots the server and drives it with WebSocket bots like a browser would
```

The server owns everything that matters: damage, deaths, XP, drops, quest
progress, money and cooldowns. The one thing the client leads on is its own
position, so movement feels instant. The server checks every step against a
distance budget (speed × elapsed time, plus what dashes, teleports and
knockback grant) and pulls a client back when it overspends. Each client
receives only the players, monsters and effects within view range, at 15
snapshots a second. Skill effects travel as small events (a projectile's
origin, angle and speed) that the client animates itself.

```
npm test             # node test/sim.js && node test/smoke.js
```
