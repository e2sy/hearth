"""The World Explorer: every kind of music on Earth, as one big dial.

A curated universe of genre stations — every inhabited continent, the
global styles that crossed every border, and the eras that raised them.
Each genre carries a handful of search seeds so the same station can
spin differently every visit. Pure data + tiny helpers: no network, no
Qt — trivially testable, and the app layer turns a genre into a queue.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Genre:
    """One dial position on the world radio."""

    key: str
    label: str
    emoji: str
    region: str
    blurb: str
    queries: tuple[str, ...]


# Ordered the way the World page reads: continents first, then the
# border-crossing styles, then the eras.
REGIONS = (
    "Africa",
    "Asia",
    "Europe",
    "Latin America",
    "Caribbean",
    "Middle East & North Africa",
    "North America",
    "Global & Electronic",
    "Eras",
)

G = Genre

GENRE_UNIVERSE: tuple[Genre, ...] = (
    # ---------------------------------------------------------- Africa
    G("afrobeat", "Afrobeat", "🥁", "Africa",
      "Fela's fire — West African funk that never sits down",
      ("afrobeat essentials", "afrobeats hits", "burna boy wizkid davido")),
    G("amapiano", "Amapiano", "🎹", "Africa",
      "South Africa's log-drum house, smooth and hypnotic",
      ("amapiano hits", "amapiano log drum mix", "kabza de small dj maphorisa")),
    G("highlife", "Highlife", "🌴", "Africa",
      "Ghana & Nigeria's golden guitar bounce",
      ("ghana highlife classics", "nigerian highlife golden era", "highlife classics")),
    G("ethio_jazz", "Ethio-Jazz", "🎷", "Africa",
      "Mulatu Astatke's smoky Addis modal jazz",
      ("ethio jazz mulatu astatke", "ethiopian jazz classics")),
    G("makossa", "Makossa", "🪘", "Africa",
      "Cameroon's bass-heavy dance groove",
      ("makossa classics", "manu dibango makossa", "cameroonian makossa hits")),
    G("taarab", "Taarab", "🎻", "Africa",
      "Zanzibar's Swahili orchestra of strings and oud",
      ("taarab zanzibar music", "swahili taarab classics")),
    # ------------------------------------------------------------ Asia
    G("kpop", "K-Pop", "💖", "Asia",
      "Seoul's idol machine — hooks engineered to orbit",
      ("kpop hits", "kpop 2026 playlist", "bts blackpink twice stray kids")),
    G("jpop", "J-Pop", "🌸", "Asia",
      "Tokyo pop with anime-openings energy",
      ("jpop hits", "japanese pop playlist", "yoasobi ado official higedan")),
    G("city_pop", "City Pop", "🌆", "Asia",
      "80s Tokyo yacht-pop — neon highways and sax",
      ("city pop 80s japan", "tatsuro yamashita mariya takeuchi", "japanese city pop groove")),
    G("jrock", "J-Rock", "🎸", "Asia",
      "Japanese rock, from stadium anthems to anime cold opens",
      ("jrock hits", "japanese rock playlist", "one ok rock radwimps jrock classics")),
    G("mandopop", "Mandopop", "🏮", "Asia",
      "Mandarin pop ballads and Taiwan's dream factories",
      ("mandopop hits", "mandarin pop classics", "jay chou jolin tsai")),
    G("cantopop", "Cantopop", "🥮", "Asia",
      "Hong Kong's silver-screen pop tradition",
      ("cantopop classics", "hong kong cantopop hits", "beyond eason chan")),
    G("bollywood", "Bollywood", "🎬", "Asia",
      "Hindi film music — the world's biggest song factory",
      ("bollywood hits", "hindi film songs playlist", "arijit singh shreya ghoshal")),
    G("bhangra", "Bhangra", "💃", "Asia",
      "Punjabi dhol energy that conquered the diaspora",
      ("bhangra hits", "punjabi bhangra playlist", "daler mehndi diljit dosanjh")),
    G("kollywood", "Kollywood", "🪔", "Asia",
      "Tamil cinema bangers — Chennai's maximalist sound",
      ("tamil hits kollywood", "tamil film songs playlist", "anirudh a r rahman tamil")),
    G("hindustani", "Hindustani Classical", "🪷", "Asia",
      "North India's raga tradition — dawn ragas to all-night jams",
      ("hindustani classical raga", "indian classical sitar tabla", "raag bhairav yaman")),
    G("carnatic", "Carnatic", "🕉️", "Asia",
      "South India's devotional classical art",
      ("carnatic classical music", "south indian classical vocal", "ms subbulakshmi")),
    G("qawwali", "Qawwali", "🕌", "Asia",
      "Sufi devotional music that lifts the roof of your chest",
      ("qawwali classics", "nusrat fateh ali khan", "sufi qawwali playlist")),
    # ---------------------------------------------------------- Europe
    G("britpop", "Britpop", "🇬🇧", "Europe",
      "90s UK guitars — attitude, anthems, and parkas",
      ("britpop anthems", "oasis blur pulp radiohead", "british 90s rock hits")),
    G("eurodance", "Eurodance", "🪩", "Europe",
      "90s continental synth-stomp built for arenas",
      ("90s eurodance hits", "eurodance classics", "ace of base eurodance playlist")),
    G("italodisco", "Italo Disco", "🛵", "Europe",
      "80s Italian synth-disco, dreamy and plastic",
      ("italo disco classics", "80s italian disco hits", "giorgio moroder italo")),
    G("flamenco", "Flamenco", "👠", "Europe",
      "Andalusian guitar, palms, and duende",
      ("flamenco guitar classics", "spanish flamenco playlist", "paco de lucia camaron")),
    G("fado", "Fado", "🕯️", "Europe",
      "Lisbon's longing — saudade sung in small rooms",
      ("fado lisboa classics", "amalia rodrigues fado", "portuguese fado playlist")),
    G("chanson", "Chanson Française", "🥐", "Europe",
      "French lyric song — Brel to Gainsbourg",
      ("chanson francaise classics", "edith piaf serge gainsbourg", "french cafe music")),
    G("balkan_brass", "Balkan Brass", "🎺", "Europe",
      "Wedding-brass madness from the Balkans",
      ("balkan brass band", "goran bregovic fanfare", "serbian trumpet hits")),
    G("nordic_folk", "Nordic Folk", "🌲", "Europe",
      "Fiddles, kulning, and fjord-air harmonies",
      ("nordic folk music", "scandinavian folk fiddle", "wardruna myrkur nordic folk")),
    G("celtic", "Celtic", "🍀", "Europe",
      "Ireland & Scotland — jigs, reels, and airy ballads",
      ("celtic folk classics", "irish traditional session", "the chieftains celtic playlist")),
    G("klezmer", "Klezmer", "🕎", "Europe",
      "Eastern European Jewish wedding music — joy with tears",
      ("klezmer classics", "jewish klezmer band", "clarinet klezmer hits")),
    # ---------------------------------------------------- Latin America
    G("reggaeton", "Reggaeton", "🔥", "Latin America",
      "Puerto Rico's dembow that runs the charts",
      ("reggaeton hits", "reggaeton perreo playlist", "bad bunny daddy yankee karol g")),
    G("salsa", "Salsa", "🌶️", "Latin America",
      "NYC-Puerto Rican-Cuban brass and clave",
      ("salsa classics", "hector lavoe willie colon", "salsa dura playlist")),
    G("bachata", "Bachata", "🥂", "Latin America",
      "Dominican guitar-heartbreak in 4/4",
      ("bachata hits", "romeo santos aventura", "dominican bachata classics")),
    G("cumbia", "Cumbia", "🌊", "Latin America",
      "Colombia's beat that drifted across a continent",
      ("cumbia sonidera classics", "colombian cumbia hits", "cumbia playlist")),
    G("bossa_nova", "Bossa Nova", "☕", "Latin America",
      "Rio's soft-focus samba jazz",
      ("bossa nova classics", "joao gilberto tom jobim", "bossa nova cafe playlist")),
    G("mpb", "MPB", "🌿", "Latin America",
      "Brazilian popular music — Caetano, Gil, Elis",
      ("mpb classics", "caetano veloso gilberto gil", "brazilian popular music playlist")),
    G("tango", "Tango", "🩰", "Latin America",
      "Buenos Aires bandoneon drama",
      ("tango classics", "carlos gardel astor piazzolla", "argentine tango music")),
    G("latin_rock", "Latin Rock", "🪨", "Latin America",
      "Rock en español — from Santana to Soda Stereo",
      ("rock en espanol classics", "soda stereo caifanes mana latin rock", "santana latin rock anthems")),
    # ------------------------------------------------------- Caribbean
    G("reggae", "Reggae", "🟩", "Caribbean",
      "Jamaica's heartbeat — one drop, forever",
      ("reggae classics", "bob marley peter tosh", "roots reggae playlist")),
    G("dancehall", "Dancehall", "🔆", "Caribbean",
      "Kingston's digital riddim machine",
      ("dancehall hits", "sean paul shabba dancehall riddim playlist", "vybz kartel popcaan")),
    G("soca", "Soca", "🥳", "Caribbean",
      "Trinidad carnival energy — jump and wave",
      ("soca hits", "trinidad carnival soca", "kes munchi soca playlist")),
    G("calypso", "Calypso", "🏝️", "Caribbean",
      "Wit and rhythm from the islands' elder statesmen",
      ("calypso classics", "harry belafonte mighty sparrow", "trinidad calypso playlist")),
    # ------------------------------------- Middle East & North Africa
    G("arabic_pop", "Arabic Pop", "🌙", "Middle East & North Africa",
      "Cairo-to-Beirut pop — oud scales over club drums",
      ("arabic pop hits", "amr diab nancy ajram", "arabic pop playlist 2026")),
    G("rai", "Raï", "🎤", "Middle East & North Africa",
      "Oran's rebel music — Cheb Khaled and friends",
      ("rai algerien classics", "cheb khaled cheb mami", "algerian rai playlist")),
    G("khaliji", "Khaliji", "🐪", "Middle East & North Africa",
      "Gulf rhythms and majlis strings",
      ("khaliji hits", "saudi khaleeji music", "gulf arabic pop classics")),
    G("anatolian_rock", "Anatolian Rock", "🧿", "Middle East & North Africa",
      "70s Turkish psych — saz fuzz and funk breaks",
      ("anatolian rock classics", "turkish 70s psych funk", "baris manco erkin koray")),
    G("persian_classical", "Persian Classical", "🪞", "Middle East & North Africa",
      "Iran's radif tradition — tar, setar, and sung poetry",
      ("persian classical music", "iranian traditional tar setar", "persian classical radif")),
    # ---------------------------------------------------- North America
    G("blues", "Blues", "🎸", "North America",
      "Delta to Chicago — the root of almost everything",
      ("blues classics", "buddy guy bb king muddy waters", "chicago delta blues playlist")),
    G("bluegrass", "Bluegrass", "🪕", "North America",
      "Appalachian pickers at lightning speed",
      ("bluegrass classics", "bill monroe earl scruggs", "bluegrass banjo fiddle playlist")),
    G("country", "Country", "🤠", "North America",
      "Nashville storytelling from honky-tonk to stadium",
      ("country classics", "johnny cash dolly parton", "country hits playlist")),
    G("motown", "Motown", "🎙️", "North America",
      "The Sound of Young America — Detroit soul pop",
      ("motown classics", "supremes temptations stevie wonder", "detroit soul hits")),
    G("funk", "Funk", "🕺", "North America",
      "The One — James Brown's gift to every groove since",
      ("funk classics", "james brown parliament funkadelic", "funk groove playlist")),
    G("gospel", "Gospel", "🙌", "North America",
      "Choirs, organs, and voices that raise roofs",
      ("gospel classics", "kirk franklin mahalia jackson", "gospel choir playlist")),
    G("nola_jazz", "New Orleans Jazz", "🎩", "North America",
      "Brass bands and second lines where jazz was born",
      ("new orleans jazz classics", "louis armstrong trad jazz", "nola brass band second line")),
    G("surf_rock", "Surf Rock", "🏄", "North America",
      "Reverb-drenched 60s California instrumentals",
      ("surf rock classics", "dick dale the ventures", "60s surf instrumental playlist")),
    # ------------------------------------------- Global & Electronic
    G("house", "House", "🏠", "Global & Electronic",
      "Chicago's four-on-the-floor, now a world language",
      ("house music classics", "frankie knuckles chicago house", "deep house playlist")),
    G("techno", "Techno", "⚙️", "Global & Electronic",
      "Detroit's machine funk, Berlin's cathedral of kick",
      ("techno classics", "berlin detroit techno", "techno warehouse playlist")),
    G("trance", "Trance", "🌌", "Global & Electronic",
      "Euphoric buildups and hands-in-the-air drops",
      ("trance classics", "above and beyond armin van buuren", "uplifting trance playlist")),
    G("drum_and_bass", "Drum & Bass", "⚡", "Global & Electronic",
      "Breakbeats at 174 BPM — London's speed heart",
      ("drum and bass classics", "liquid dnb playlist", "goldie ltj bukem dnb")),
    G("dubstep", "Dubstep", "🔊", "Global & Electronic",
      "South London bass weight, half-time wobble",
      ("dubstep classics", "deep meditational dubstep", "skream benga burial dubstep")),
    G("ambient", "Ambient", "☁️", "Global & Electronic",
      "Music for airports, forests, and long stares",
      ("ambient classics", "brian eno stars of the lid", "ambient drone playlist")),
    G("lofi", "Lo-Fi Beats", "📚", "Global & Electronic",
      "Dusty drums to study, drift, and unwind to",
      ("lofi hip hop beats", "lofi study playlist", "chillhop beats to relax")),
    G("synthwave", "Synthwave", "🕶️", "Global & Electronic",
      "Retro-futurist neon soundtracks for imaginary films",
      ("synthwave classics", "retrowave outrun playlist", "kavinsky the midnight synthwave")),
    G("jazz", "Jazz", "🎺", "Global & Electronic",
      "America's art form, adopted by every continent",
      ("jazz classics", "miles davis john coltrane bill evans", "jazz standards playlist")),
    G("classical", "Classical", "🎼", "Global & Electronic",
      "Six centuries of orchestral and chamber mastery",
      ("classical music masterpieces", "beethoven mozart bach", "orchestral classics playlist")),
    G("hiphop", "Hip-Hop", "🎤", "Global & Electronic",
      "The culture that swallowed the world — boom bap to drill",
      ("hip hop classics", "boom bap essentials", "kendrick nas tupac hip hop playlist")),
    G("rnb", "R&B / Soul", "💜", "Global & Electronic",
      "Silky voices and slow-burn grooves",
      ("rnb soul classics", "neo soul playlist", "dangelo erykah badu sza")),
    G("metal", "Metal", "🤘", "Global & Electronic",
      "Riffs of doom — thrash, doom, power, and beyond",
      ("metal classics", "metallica iron maiden black sabbath", "heavy metal playlist")),
    G("punk", "Punk", "🧷", "Global & Electronic",
      "Three chords and the truth, worldwide",
      ("punk classics", "ramones clash dead kennedys", "punk rock anthems playlist")),
    G("indie", "Indie Rock", "🚲", "Global & Electronic",
      "Guitars, feelings, and dorm-room epics",
      ("indie rock classics", "arctic monkeys the strokes", "indie playlist 2026")),
    # ------------------------------------------------------------ Eras
    G("sixties", "60s Oldies", "📼", "Eras",
      "The decade the charts went global",
      ("60s oldies classics", "beatles beach boys supremes", "sixties hits playlist")),
    G("seventies", "70s Classics", "🎞️", "Eras",
      "Vinyl warmth — rock, soul, and disco's birth",
      ("70s classics", "fleetwood mac pink floyd stevie wonder", "seventies hits playlist")),
    G("eighties", "80s Hits", "📼", "Eras",
      "Synths, snares, and maximum drama",
      ("80s hits classics", "michael jackson madonna prince", "eighties playlist")),
    G("nineties", "90s Throwbacks", "💿", "Eras",
      "CD-era everything — grunge to eurodance",
      ("90s throwback hits", "backstreet boys spice girls nirvana", "nineties playlist")),
    G("two_thousands", "2000s Hits", "🔉", "Eras",
      "MP3-player nostalgia — pop-punk to R&B",
      ("2000s hits", "eminem justin timberlake beyonce", "y2k playlist")),
    G("twenty_tens", "2010s Bangers", "📲", "Eras",
      "The streaming decade's biggest moments",
      ("2010s bangers", "adele drake taylor swift", "2010s throwback playlist")),
)

assert all(g.region in REGIONS for g in GENRE_UNIVERSE), "region typo in universe"

_UNIVERSE_INDEX: dict[str, Genre] = {g.key: g for g in GENRE_UNIVERSE}


# ------------------------------------------------------------------ API

def genres() -> tuple[Genre, ...]:
    """Every station in the universe, curated order."""
    return GENRE_UNIVERSE


def genre(key: str) -> Genre | None:
    """Look up a genre by key (None when unknown)."""
    return _UNIVERSE_INDEX.get(key)


def genres_by_region() -> list[tuple[str, list[Genre]]]:
    """Region -> its genres, in REGIONS order (only non-empty regions)."""
    out: list[tuple[str, list[Genre]]] = []
    for region in REGIONS:
        bucket = [g for g in GENRE_UNIVERSE if g.region == region]
        if bucket:
            out.append((region, bucket))
    return out


def station_query(g: Genre, spin: int = 0) -> str:
    """The search seed for this visit — spins rotate through the seeds."""
    seeds = g.queries or (g.label,)
    return seeds[int(spin) % len(seeds)]


def random_genre(rng: random.Random | None = None) -> Genre:
    """A surprise dial position."""
    return (rng or random.Random()).choice(GENRE_UNIVERSE)


def match(genre_: Genre, needle: str) -> bool:
    """Case-insensitive filter over label, region, and blurb."""
    hay = f"{genre_.label} {genre_.region} {genre_.blurb}".lower()
    return needle.lower().strip() in hay
