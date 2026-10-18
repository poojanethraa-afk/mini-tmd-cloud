# Mini TMD Cloud

A small, self-built model of a **multi-tenant cloud PACS**. Each customer (hospital or practice) gets its own isolated environment: an [Orthanc](https://www.orthanc-server.com/) PACS with a PostgreSQL index, started from one shared Docker Compose blueprint.

I built it to learn the day-to-day work of a Customer Implementation Engineer: setting up customer environments, running containerised services, and working with DICOM data and SQL.

> **Data protection:** only public DICOM sample files that ship with `pydicom` are used. No real patient data is used anywhere in this project.

---

## Architecture

```
            one blueprint (docker-compose.yml) + one settings file per customer
                                       |
            +--------------------------+--------------------------+
            |                                                     |
   Project "klinik-a"                                    Project "praxis-b"
   customers/klinik-a.env                                customers/praxis-b.env
   +-------------------------------+                     +-------------------------------+
   | orthanc  (PACS + web viewer)  |                     | orthanc  (PACS + web viewer)  |
   |   :8042 web / REST API        |                     |   :8043 web / REST API        |
   |   :4242 DICOM                 |                     |   :4243 DICOM                 |
   |   volume: orthanc-storage     |                     |   volume: orthanc-storage     |
   |            |                  |                     |            |                  |
   | db  (PostgreSQL 18, index)    |                     | db  (PostgreSQL 18, index)    |
   |   internal only, no port      |                     |   internal only, no port      |
   |   volume: pgdata              |                     |   volume: pgdata              |
   +-------------------------------+                     +-------------------------------+
```

| Component | Role |
|---|---|
| `db`: PostgreSQL 18 | Stores Orthanc's **index** (patients, studies, series, instances). It's only reachable inside the project network. |
| `orthanc`: `orthancteam/orthanc:26.9.1` | The PACS. It receives DICOM on port 4242 and serves the web UI (Orthanc Explorer 2), REST API, DICOMweb and Stone Web Viewer on port 8042. |
| `pgdata` volume | Keeps the database files across container restarts |
| `orthanc-storage` volume | Holds the DICOM files themselves. The index lives in the database and the image files live on storage. |

**Design decisions**

- **Pinned image versions** (`postgres:18`, `orthancteam/orthanc:26.9.1`) instead of `latest`, so every customer environment is reproducible.
- **Healthcheck plus `depends_on: service_healthy`.** Orthanc starts only when `pg_isready` reports that the database accepts connections.
- **Isolation per customer.** Docker Compose project names (`-p <customer>`) give each customer its own containers, network and volumes, so one customer can never see another's images.
- **No secrets in Git.** Credentials live in `.env` and `customers/*.env`, which are git-ignored. The compose file contains only `${...}` placeholders.
- **The database is not exposed to the host.** Only the ports that are actually needed (8042 and 4242) are published.

---

## Project structure

```
mini-tmd-cloud/
├── docker-compose.yml     # shared blueprint: db + orthanc
├── onboard.ps1            # onboarding script: one command per customer
├── explore_dicom.py       # reads DICOM header fields with pydicom
├── load_dicom.py          # turns 144 sample DICOM headers into load.sql
├── customers/             # one settings file per customer (git-ignored)
│   ├── klinik-a.env
│   └── praxis-b.env
├── .env                   # default settings for local testing (git-ignored)
└── .gitignore
```

---

## Customer settings

Each customer file in `customers/` defines:

| Variable | Purpose | Example |
|---|---|---|
| `POSTGRES_USER` | Database user | — |
| `POSTGRES_PASSWORD` | Database password, unique per customer | — |
| `POSTGRES_DB` | Database name | — |
| `ORTHANC_PASSWORD` | Password of the Orthanc `admin` web user | — |
| `ORTHANC_HTTP_PORT` | Host port for the web UI / REST API | `8042`, `8043`, … |
| `ORTHANC_DICOM_PORT` | Host port for DICOM | `4242`, `4243`, … |

Every customer needs **its own ports**, because two environments can't publish the same host port.

---

## Runbook: onboarding a new customer

1. **Create the settings file.** Copy an existing customer file to `customers/<customer>.env`. Set new passwords and the next free ports.
2. **Protect it.** Make sure `customers/<customer>.env` is covered by `.gitignore`, then check with `git status` that the file does **not** appear.
3. **Validate the configuration:**
   ```powershell
   .\onboard.ps1 <customer>
   ```
   The script runs `docker compose -p <customer> --env-file customers/<customer>.env config --quiet`. No output means the configuration is valid.
4. **Start the environment** (manually for now; see Roadmap):
   ```powershell
   docker compose -p <customer> --env-file customers/<customer>.env up -d
   ```
5. **Check the status:**
   ```powershell
   docker compose -p <customer> ps
   ```
   `db` should show `(healthy)` and `orthanc` should be `Up`.
6. **Hand over:** the web UI is at `http://localhost:<ORTHANC_HTTP_PORT>` (user `admin`), and modalities send to DICOM port `<ORTHANC_DICOM_PORT>`.

### Useful commands

| Task | Command |
|---|---|
| Start only the database | `docker compose -p <customer> --env-file customers/<customer>.env up -d db` |
| Show logs | `docker compose -p <customer> logs -f orthanc` |
| Open SQL shell | `docker compose -p <customer> --env-file customers/<customer>.env exec db psql -U <user> -d <db>` |
| Stop (data is kept) | `docker compose -p <customer> down` |
| Stop **and delete all data** ⚠️ | `docker compose -p <customer> down -v` |

---

## DICOM metadata

`explore_dicom.py` opens a sample CT from `pydicom` and prints the header fields a PACS sorts and searches by:

```
PatientID: 1CT1
Modality: CT
StudyDate: 20040119
BodyPartExamined: UNKNOWN
```

Run it with:

```powershell
.venv\Scripts\activate
python explore_dicom.py
```

Optional fields such as `BodyPartExamined` are read with `ds.get(..., "UNKNOWN")`, because not every file contains them.

### Loading DICOM metadata into PostgreSQL

`load_dicom.py` scans all sample files that ship with `pydicom` (176 files, 144 of them DICOM objects with a modality). It writes one `INSERT` per file into `load.sql`, which is then loaded into the customer's database.

Because the database port is not exposed, the script generates SQL instead of connecting directly. This also lets you review the changes before applying them.

1. Create the table (once per customer):
   ```sql
   CREATE TABLE studies (
       id SERIAL PRIMARY KEY,
       patient_id TEXT,
       modality TEXT,
       study_date DATE,
       body_part TEXT
   );
   ```
2. Generate the SQL:
   ```powershell
   python load_dicom.py
   ```
3. Load it into Klinik A's database:
   ```powershell
   Get-Content load.sql | docker compose -p klinik-a --env-file customers/klinik-a.env exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
   ```

These are the details the script handles:

- DICOM dates (`YYYYMMDD`) are converted to SQL dates (`YYYY-MM-DD`).
- A missing date is stored as `NULL`. 9 of the 144 files have no date.
- Single quotes in values are escaped (`'` becomes `''`).
- Unreadable files, and files without a modality, are skipped instead of crashing the run.

Result: **144 studies** across 12 modalities (CT 64, MR 27, OT 23, RTDOSE 7, US 5, NM 4, RTPLAN 4, CR 3, SR 3, SEG 2, ECG 1, RTSTRUCT 1), with study dates from 1995 to 2020.

Example report (studies per modality):

```sql
SELECT modality, COUNT(*) AS studies
FROM studies
GROUP BY modality
ORDER BY studies DESC;
```

---

## Troubleshooting

These are real problems I ran into while building this project:

| Symptom | Cause | Fix |
|---|---|---|
| `failed to connect to the docker API … daemon is running` | Docker Desktop (the daemon) is not running | Start Docker Desktop and wait for "Engine running" |
| `TLS handshake timeout` / `server gave HTTP response to HTTPS client` while pulling | An unstable or interfering network connection | Retry `docker pull` (finished layers are kept), or switch networks |
| PostgreSQL 18 data is not persisted, or the container fails to start | Since PostgreSQL 18 the image's data directory is `/var/lib/postgresql` (earlier versions used `/var/lib/postgresql/data`) | Mount the volume at `/var/lib/postgresql` and read the release notes before upgrading |
| `services.db.volumes must be a array` | A missing `- ` list marker in YAML | Write list items as `- name:path` |
| `… is missing a mount target` | A space after the colon (`name: /path`) makes YAML read the item as a mapping | Write `name:/path` with no space |
| Orthanc ignores a database setting | Wrong env var name. Orthanc uses `__` for each nesting level (`ORTHANC__POSTGRESQL__HOST`) and `_` between words of one setting (`ORTHANC__REGISTERED_USERS`) | Check the variable names against the Orthanc Docker documentation |
| Database login fails although the password is correct | A space after `=` in a `.env` file becomes part of the value | Write `NAME=value` with no spaces |
| Orthanc exits right after "Orthanc has started" (exit code 139) | The log shows `The Stone Web viewer requires the DICOMweb plugin to be installed` | Also set `DICOM_WEB_PLUGIN_ENABLED: 'true'`. The viewer loads its images through DICOMweb. |
| `port is already allocated` | Two customers use the same host port | Give each customer unique ports |

---

## Roadmap

- [x] Run the full stack end to end: upload a sample CT and MR to Klinik A, then view them in the Stone Web Viewer
- [x] `studies` table in PostgreSQL plus a script that loads DICOM metadata into it
- [ ] More SQL reports, e.g. studies per year and a data-quality check (missing dates and body parts)
- [ ] `onboard.ps1`: check that the customer file exists, start the environment with `up -d`, and print the URL
- [ ] Health-check script and a GitHub Actions workflow that validates the compose file
- [ ] HL7 example: match an order message to a DICOM study

### What production would need beyond this demo

TLS for the web and DICOM endpoints, a secrets manager instead of `.env` files, automated backups and restore tests for both volumes, monitoring and alerting, role-based access control, audit logging, and the controls that BSI C5 and ISO 27001 require.
