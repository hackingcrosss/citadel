"""Random project codename generator using fictional and historical names."""

import random

# Fictional characters + historical figures suitable for corporate contexts.
# No dictators, criminals, or otherwise controversial figures.
# Kept lowercase for slug use — display can title-case as needed.
CODENAMES = [
    # Muppets / Sesame Street
    'kermit', 'fozzie', 'gonzo', 'scooter', 'waldorf', 'statler', 'beaker',
    'rizzo', 'pepe', 'sweetums', 'rowlf', 'beauregard',
    # Animated series
    'clawhauser', 'bogo', 'gazelle', 'yax', 'finnick',
    'archer', 'krieger', 'lana', 'cyril', 'malory', 'pam', 'cheryl',
    'sterling', 'woodhouse', 'figgis', 'slater',
    # Comics / Graphic novels
    'gambit', 'rogue', 'cable', 'domino', 'warpath', 'colossus',
    'mystique', 'havok', 'banshee', 'sunspot', 'forge', 'dazzler',
    'magik', 'polaris', 'fantomex', 'psylocke',
    'deadpool', 'nightcrawler', 'jubilee',
    # Star Wars
    'mando', 'grogu', 'ahsoka', 'hondo', 'fennec',
    'greef', 'kuiil',
    # Sci-fi movies/shows
    'ripley', 'newt', 'dallas', 'lambert',
    'deckard', 'gaff',
    'neo', 'morpheus', 'trinity', 'dozer', 'tank',
    'korben', 'leeloo',
    # Spy/thriller
    'bourne', 'ethan', 'benji', 'luther', 'ilsa', 'brandt',
    'vesper', 'leiter', 'moneypenny',
    # Fantasy / Lord of the Rings
    'strider', 'legolas', 'gimli', 'gandalf', 'faramir',
    'eowyn', 'eomer', 'theoden', 'treebeard', 'radagast',
    # Books / literary
    'atticus', 'gatsby', 'scout', 'marlowe',
    'poirot', 'marple', 'reacher',
    # Anime / manga
    'spike', 'jet', 'faye', 'motoko', 'batou', 'togusa',
    # Video games
    'cortana', 'samus', 'link', 'geralt',
    'ezio', 'altair', 'kassandra', 'bayek',
    # Westerns
    'eastwood', 'blondie', 'mortimer',
    'holliday', 'earp',

    # ── Historical figures (scientists, explorers, artists, thinkers) ─────────
    # Scientists & inventors
    'curie', 'darwin', 'faraday', 'galileo', 'kepler', 'lovelace',
    'maxwell', 'newton', 'pasteur', 'planck', 'tesla', 'turing',
    'hopper', 'euler', 'gauss', 'fermi', 'bohr', 'hawking',
    'edison', 'babbage', 'copernicus', 'herschel', 'brahe',
    'flemming', 'mendel', 'linnaeus', 'laplace', 'leibniz',
    # Explorers & navigators
    'amundsen', 'shackleton', 'magellan', 'drake', 'cook',
    'earhart', 'lindbergh', 'hillary', 'tenzing', 'cousteau',
    'polo', 'vespucci', 'humboldt', 'livingstone', 'nansen',
    # Artists, composers & writers
    'vermeer', 'monet', 'vivaldi', 'chopin', 'handel',
    'rembrandt', 'caravaggio', 'fibonacci', 'archimedes',
    'austen', 'bronte', 'tolkien', 'verne', 'shelley', 'twain',
    # Philosophers & thinkers
    'aristotle', 'plato', 'socrates', 'hypatia', 'seneca',
    'confucius', 'descartes', 'spinoza', 'voltaire', 'locke',
    # Leaders, reformers & pioneers (universally respected)
    'mandela', 'nightingale', 'tubman', 'pankhurst',
    'armstrong', 'gagarin', 'ride', 'aldrin',
    'gutenberg', 'marconi', 'berners-lee',
]

# Deduplicate while preserving order
_seen = set()
_unique = []
for _c in CODENAMES:
    if _c not in _seen:
        _seen.add(_c)
        _unique.append(_c)
CODENAMES = _unique


def generate_codename(existing_codes=None):
    """Return a unique codename not in `existing_codes`.

    Tries a random pick first. If all base names are taken, appends a
    numeric suffix (e.g. 'kermit-2').
    """
    existing = {c.lower() for c in (existing_codes or [])}
    pool = [c for c in CODENAMES if c not in existing]
    if pool:
        return random.choice(pool)

    # All base names taken — append suffix
    for _ in range(200):
        base = random.choice(CODENAMES)
        suffix = random.randint(2, 99)
        candidate = f'{base}-{suffix}'
        if candidate not in existing:
            return candidate

    # Fallback
    import secrets
    return f'op-{secrets.token_hex(4)}'
