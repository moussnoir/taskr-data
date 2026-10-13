"""Taskr — base mondiale des commerces de services, construite chaque semaine.

Source : Overture Maps Foundation (lieux / places), licence CDLA-Permissive-2.0
(+ certaines sources sous ODbL / autres licences libres indiquées par Overture).
On ne garde que les métiers utiles à Taskr, les lieux jugés fiables et non fermés,
puis on découpe le monde en carrés de 1° publiés en JSON compact sur GitHub Pages.
"""
import json, math, os, re, sys, time, urllib.request, shutil
import duckdb

OUT = 'out'
MAX_BYTES = 950 * 1024 * 1024          # limite GitHub Pages : 1 Go
MIN_CONF = float(os.environ.get('MIN_CONF', '0.6'))

# métier Overture (catégorie) → (catégorie Taskr, métier affiché). Ordre = priorité.
TRADES = [
    (r'plumb', 'Maison', 'Plombier'),
    (r'electrician', 'Maison', 'Électricien'),
    (r'locksmith', 'Maison', 'Serrurier'),
    (r'hvac|heating|air_conditioning', 'Maison', 'Chauffage · climatisation'),
    (r'roofing|roofer', 'Maison', 'Couvreur'),
    (r'carpent|joiner|cabinet_?maker', 'Maison', 'Menuisier'),
    (r'painting_contractor|house_painter|painter', 'Maison', 'Peintre'),
    (r'tiling|tile_install|flooring', 'Maison', 'Carreleur · sols'),
    (r'handyman|home_repair|contractor', 'Maison', 'Artisan · travaux'),
    (r'landscap|gardener|lawn|tree_service', 'Maison', 'Jardinier · paysagiste'),
    (r'house_cleaning|home_cleaning|cleaning_service|janitorial|maid', 'Maison', 'Ménage · nettoyage'),
    (r'mover|moving_company|removal', 'Maison', 'Déménagement'),
    (r'appliance_repair', 'Maison', 'Réparation électroménager'),
    (r'dry_clean|laundr', 'Maison', 'Pressing · laverie'),
    (r'tailor|sewing|alteration', 'Maison', 'Couture · retouches'),
    (r'shoe_repair|cobbler', 'Maison', 'Cordonnier'),
    (r'barber', 'Bien-être', 'Barbier'),
    (r'hair_salon|hairdresser|hair_stylist|hair_care', 'Bien-être', 'Coiffure'),
    (r'nail_salon|beauty_salon|beauty|esthetic|cosmetolog|makeup', 'Bien-être', 'Beauté'),
    (r'massage|spa\b|day_spa', 'Bien-être', 'Massage · spa'),
    (r'personal_trainer|fitness_trainer|yoga|pilates', 'Cours', 'Coach · yoga'),
    (r'driving_school', 'Cours', 'Auto-école'),
    (r'tutor|language_school|music_school|music_lesson|educational_service', 'Cours', 'Cours · soutien'),
    (r'photograph', 'Événement', 'Photographe'),
    (r'cater', 'Événement', 'Traiteur'),
    (r'event_plan|wedding_plan|dj_service|party_equipment', 'Événement', 'Événementiel'),
    (r'computer_repair|it_service|computer_service', 'Tech', 'Informatique'),
    (r'mobile_phone_repair|phone_repair|electronics_repair', 'Tech', 'Réparation téléphones · électronique'),
    (r'pet_groom|dog_groom|pet_sitting|dog_walk|pet_boarding', 'Animaux', 'Toilettage · garde d\'animaux'),
    (r'auto_repair|car_repair|mechanic|car_wash|auto_detailing', 'Auto', 'Garage · mécanique'),
]
PATTERN = '|'.join(t[0] for t in TRADES)
CATS = ['Maison', 'Bien-être', 'Cours', 'Événement', 'Tech', 'Animaux', 'Auto']


def latest_release():
    with urllib.request.urlopen('https://stac.overturemaps.org/catalog.json', timeout=60) as r:
        cat = json.load(r)
    rel = cat.get('latest')
    if not rel:
        raise SystemExit('Release Overture introuvable')
    return rel


def classify(text):
    # la catégorie principale (1er mot) d'abord, puis les catégories secondaires
    text = text or ''
    for part in (text.split(' ', 1)[0], text):
        for rx, cat, label in TRADES:
            if re.search(rx, part):
                return CATS.index(cat), label
    return None


def main():
    rel = os.environ.get('TEST_REL') or latest_release()
    src = os.environ.get('TEST_SRC') or f's3://overturemaps-us-west-2/release/{rel}/theme=places/type=place/*'
    print('Overture release', rel, flush=True)
    con = duckdb.connect()
    if not os.environ.get('TEST_SRC'):
        con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    con.execute("SET enable_progress_bar=false;")
    cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{src}', hive_partitioning=1) LIMIT 0").fetchall()}
    print('columns', sorted(cols), flush=True)
    if 'taxonomy' in cols:
        cat_expr = "lower(coalesce(taxonomy.primary,'') || ' ' || coalesce(array_to_string(taxonomy.alternates,' '),'') || ' ' || coalesce(basic_category,''))"
    else:
        cat_expr = "lower(coalesce(categories.primary,'') || ' ' || coalesce(array_to_string(categories.alternate,' '),''))"
    status_ok = "(operating_status IS NULL OR lower(CAST(operating_status AS VARCHAR)) LIKE '%open%')" if 'operating_status' in cols else 'TRUE'
    t0 = time.time()
    con.execute(f"""
      COPY (
        SELECT id,
               names.primary AS name,
               {cat_expr} AS cat,
               CAST(round((bbox.ymin + bbox.ymax) / 2, 5) AS DOUBLE) AS lat,
               CAST(round((bbox.xmin + bbox.xmax) / 2, 5) AS DOUBLE) AS lng,
               phones[1] AS phone,
               websites[1] AS web,
               addresses[1].freeform AS street,
               addresses[1].locality AS city,
               addresses[1].country AS cc,
               CAST(round(confidence, 2) AS DOUBLE) AS conf,
               len(sources) AS nsrc
        FROM read_parquet('{src}', hive_partitioning=1)
        WHERE names.primary IS NOT NULL
          AND confidence >= {MIN_CONF}
          AND {status_ok}
          AND regexp_matches({cat_expr}, '{PATTERN}')
      ) TO 'places.parquet' (FORMAT PARQUET)
    """)
    n = con.execute("SELECT count(*) FROM 'places.parquet'").fetchone()[0]
    print(f'{n} lieux retenus en {time.time() - t0:.0f}s', flush=True)
    for row in con.execute("SELECT cc, count(*) c FROM 'places.parquet' GROUP BY 1 ORDER BY 2 DESC LIMIT 40").fetchall():
        print('  ', row, flush=True)

    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT + '/t', exist_ok=True)
    conf_floor = MIN_CONF
    while True:
        total, tiles = write_tiles(con, conf_floor)
        if total <= MAX_BYTES or conf_floor >= 0.95:
            break
        conf_floor = round(conf_floor + 0.05, 2)
        print(f'trop gros ({total/1e6:.0f} Mo) → confiance min {conf_floor}', flush=True)
        shutil.rmtree(OUT + '/t'); os.makedirs(OUT + '/t')
    meta = {
        'release': rel, 'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'min_confidence': conf_floor,
        'fields': ['id', 'name', 'cat', 'trade', 'lat', 'lng', 'phone', 'web', 'street', 'city', 'cc', 'conf', 'nsrc'],
        'cats': CATS, 'tiles': tiles, 'bytes': total,
        'attribution': '© Overture Maps Foundation (CDLA-Permissive-2.0) et sources partenaires : https://docs.overturemaps.org/attribution/',
    }
    with open(OUT + '/index.json', 'w') as f:
        json.dump(meta, f, separators=(',', ':'))
    with open(OUT + '/index.html', 'w') as f:
        f.write('<meta charset="utf-8"><h1>Taskr data</h1><p>Commerces de services issus d\'Overture Maps, mis à jour chaque semaine. '
                + meta['attribution'] + '</p><pre>' + json.dumps({k: v for k, v in meta.items() if k != 'tiles'}, indent=1) + '</pre>')
    print(f'{len(tiles)} carrés, {total/1e6:.0f} Mo', flush=True)


def write_tiles(con, floor_conf):
    cur = con.execute(f"""
      SELECT CAST(floor(lat) AS INT) ty, CAST(floor(lng) AS INT) tx, id, name, cat, lat, lng, phone, web, street, city, cc, conf, nsrc
      FROM 'places.parquet' WHERE conf >= {floor_conf} ORDER BY ty, tx
    """)
    total, tiles, key, buf = 0, {}, None, []

    def flush():
        nonlocal total
        if key is None or not buf:
            return
        name = f'{key[0]}_{key[1]}.json'
        data = json.dumps({'v': 1, 'r': buf}, ensure_ascii=False, separators=(',', ':'))
        with open(f'{OUT}/t/{name}', 'w', encoding='utf-8') as f:
            f.write(data)
        total += len(data.encode('utf-8'))
        tiles[f'{key[0]}_{key[1]}'] = len(buf)

    while True:
        rows = cur.fetchmany(20000)
        if not rows:
            break
        for ty, tx, id_, name, cat, lat, lng, phone, web, street, city, cc, conf, nsrc in rows:
            k = (ty, tx)
            if k != key:
                flush(); key, buf = k, []
            c = classify(cat)
            if not c:
                continue
            buf.append([id_, name, c[0], c[1], lat, lng, phone or '', web or '', street or '', city or '', cc or '', conf, nsrc or 1])
    flush()
    return total, tiles


if __name__ == '__main__':
    main()
