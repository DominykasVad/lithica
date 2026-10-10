# Upgrading

## PostgreSQL 11 to 17

The compose files now run PostgreSQL 17. A data directory created by
PostgreSQL 11 cannot be opened by 17: the server stops at startup with
`database files are incompatible with server`. The data has to be dumped
from 11 and restored into 17. Nothing in the data directory is converted in
place, so the old directory stays intact until you delete it.

The commands assume the layout from [INSTALL.md](INSTALL.md): you are in the
repository root, `.env` holds `POSTGRES_USER`, `POSTGRES_PASSWORD` and
`MOUNT_SQL`, and the database service is called `sql`. If you set
`POSTGRES_DB`, use it wherever `$POSTGRES_USER` is given as the database
name below.

1. Load the settings into your shell and stop everything except the
   database. Do this **before** updating `docker-compose.yml`, while the
   `sql` service is still PostgreSQL 11:

    ```console
    user@host:lithica$ set -a; . ./.env; set +a
    user@host:lithica$ docker compose stop server client
    user@host:lithica$ docker compose up -d sql
    ```

2. Dump the database to a file outside the data directory and check that
   the file is not empty:

    ```console
    user@host:lithica$ docker compose exec -T sql pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_USER" > lithica-pg11.dump
    user@host:lithica$ ls -lh lithica-pg11.dump
    ```

3. Stop the stack and move the old data directory aside. Keep it until the
   upgrade is verified:

    ```console
    user@host:lithica$ docker compose down
    user@host:lithica$ sudo mv "$MOUNT_SQL" "$MOUNT_SQL.pg11"
    user@host:lithica$ sudo mkdir "$MOUNT_SQL"
    ```

4. Update the source (or edit `docker-compose.yml` so that the `sql` service
   uses `image: postgres:17`), then start only the database. It initialises
   an empty PostgreSQL 17 data directory:

    ```console
    user@host:lithica$ docker compose up -d sql
    user@host:lithica$ docker compose exec -T sql pg_isready -U "$POSTGRES_USER"
    ```

5. Restore the dump:

    ```console
    user@host:lithica$ docker compose exec -T sql pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_USER" --no-owner < lithica-pg11.dump
    ```

6. Start everything and check that your posts, tags and users are there:

    ```console
    user@host:lithica$ docker compose up -d
    ```

7. Once you are satisfied, delete `"$MOUNT_SQL.pg11"`. Keep
   `lithica-pg11.dump` as a backup for as long as you like.

### If you already started PostgreSQL 17 on the old directory

PostgreSQL 17 refuses to start and does not modify the old files. Stop the
stack and take the dump with a temporary PostgreSQL 11 container instead of
steps 1 and 2, then continue from step 3:

```console
user@host:lithica$ set -a; . ./.env; set +a
user@host:lithica$ docker compose down
user@host:lithica$ docker run -d --name lithica-pg11 -v "$MOUNT_SQL:/var/lib/postgresql/data" postgres:11-alpine
user@host:lithica$ docker exec lithica-pg11 pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_USER" > lithica-pg11.dump
user@host:lithica$ docker rm -f lithica-pg11
```

### Rolling back

Stop the stack, put the `postgres:11-alpine` image back in
`docker-compose.yml`, and move `"$MOUNT_SQL.pg11"` back to `"$MOUNT_SQL"`.
