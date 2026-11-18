# Feeder Import

The `Feeder` folder is the default place for spreadsheet files used by:

```bash
python manage.py feeder_import
```

The command imports an exhibition and its pieces through Django models, so it uses whatever database is configured in the repository's `.env`. If `DB_TYPE=postgres`, it writes to PostgreSQL. If `DB_TYPE=sqlite`, it writes to `db.sqlite3`.

## Spreadsheet Format

Supported file types:

- `.ods`
- `.xlsx`
- `.xlsm`

Expected structure:

```text
                Image 1         Image 2         Image 3
Name            Piece A         Piece B         Piece C
Artist          Artist A        Artist B        Artist C
Date            1900            1950            2000
Description     Text A          Text B          Text C
```

Rules:

- The filename without extension is the exhibition title.
- The first column contains attribute names.
- Each following column is one piece.
- The `Name` row identifies the piece.
- Images should be embedded in the first row above each piece column.
- Empty piece names are ignored.

## Basic Usage

To import or update every supported spreadsheet in `Feeder`, run:

```bash
source ~/MIP/venv/bin/activate
python manage.py feeder_import
```

With the Compose services running, use:

```bash
sudo docker compose exec web python manage.py feeder_import
```

Files are processed alphabetically. Each spreadsheet is imported independently,
so a spreadsheet with an expected format/read error is reported and the command
continues with the remaining files. The command exits with an error after the
batch if any files failed.

To choose a specific file:

```bash
python manage.py feeder_import "Removable Storage.ods"
```

or:

```bash
python manage.py feeder_import "Feeder/Removable Storage.ods"
```

To assign the imported exhibition to a specific curator:

```bash
python manage.py feeder_import "Removable Storage.ods" --admin diogo
```

`--admin` accepts a username or email address.

## Import Behavior

The importer is incremental:

- If the exhibition does not exist, it is created.
- If the exhibition already exists with the same title, it is reused.
- If a piece with the same `Name` already exists in that exhibition, it is updated only when attributes changed.
- If a piece is new, it is created.
- If a piece already exists and has no changes, it is counted as ignored.

So this output is normal after a successful previous import:

```text
Imported "Removable Storage": 0 created, 0 updated, 16 ignored, 10 attributes.
```

It means the pieces were found and no spreadsheet changes were needed.

## Curator Visibility

The `/exhibitions` page only shows exhibitions assigned to the logged-in user through the exhibition `admins` relation.

Command-line imports now assign imported exhibitions to all superusers by default. If an exhibition already existed before that behavior, run:

```bash
source ~/MIP/venv/bin/activate
python manage.py assign_superusers
```

This assigns all existing museums and exhibitions to all superusers.

To assign everything to one curator instead:

```bash
python manage.py assign_superusers --admin diogo
```

## PostgreSQL Notes

PostgreSQL requires a running database server, database, database user, and matching password in `.env`.

Check the configured database:

```bash
source ~/MIP/venv/bin/activate
python manage.py diffsettings | grep DATABASES
```

Run migrations before importing into a fresh PostgreSQL database:

```bash
python manage.py migrate
```

Restart `runserver`, or recreate the `web` service, after changing `.env`; a running Django process keeps the settings it loaded when it started.

## Troubleshooting

If `/exhibitions` looks empty after import:

1. Confirm you restarted `runserver` after changing databases.
2. Run `python manage.py assign_superusers`.
3. Log in again and reload `/exhibitions`.

If the import reports `ignored`, that does not mean failure. It means those pieces already exist and did not need updates.

To retry only one failed spreadsheet, pass its filename explicitly.
