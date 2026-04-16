# nihil-resources

`nihil-resources` is the shared, versioned resource layer for Nihil.

The goal is not to become a giant dump of random binaries.
The goal is to keep a small, explicit, reviewable set of team resources that can be mounted into every Nihil container.

This is where team defaults, portable helper scripts, small curated wordlists, webshells, cheat sheets, and fetch recipes should live.

## Positioning

Nihil already has a working contract for host-side resources:

- the wrapper mounts `my_resources.path` into the container as `/opt/my-resources`
- the image runtime automatically applies `setup/` from that mount

That means this repository can be used immediately without changing the wrapper:

1. clone `nihil-resources`
2. point `~/.nihil/config.yml` to this repository
3. start a container

Example:

```yaml
my_resources:
  enabled: true
  path: /home/you/dev/nihil-resources
```

`setup/` will be applied automatically.
Everything else stays available inside the container under `/opt/my-resources/...`.

## Philosophy

Exegol-resources is useful as a reference, but Nihil should keep a different model:

- prefer manifests and pinned sources over opaque binary dumps
- keep text and small portable artifacts in Git
- keep heavy or fast-moving payloads opt-in and syncable
- never mix engagement loot or secrets into shared resources
- organize by operational use, not by vendor branding

## Repository layout

```text
nihil-resources/
├── setup/                  # automatically applied by Nihil runtime
│   ├── zsh/
│   ├── nvim/
│   └── tmux/
├── active-directory/       # AD/internal operator resources
├── linux/                  # Linux helpers, enum, privesc, pivot
├── windows/                # Windows portable helpers
├── web/                    # webshells, templates, API helpers
├── wordlists/              # small curated lists only
├── cheatsheets/            # operator notes and quick references
├── bin/                    # tiny helper wrappers added to PATH
├── catalog/                # declarative resource catalog and profiles
└── scripts/                # validation and sync tooling
```

## What Goes Where

`setup/`
- Team shell/editor defaults.
- Must stay compatible with Nihil's current runtime loader.

`active-directory/`
- Portable AD scripts, enum helpers, templates, relay notes, bloodhound helpers.

`linux/`
- Static Linux enum/privesc helpers, pivot tools, transfer helpers.

`windows/`
- Portable Windows operator files that are still small enough and safe enough to keep here.

`web/`
- Webshells, request templates, fuzz payloads, nuclei snippets, GraphQL helpers.

`wordlists/`
- Small hand-curated lists only.
- Do not mirror SecLists here.

`cheatsheets/`
- Team notes, one-pagers, decision trees, syntax reminders.

`bin/`
- Tiny wrappers that make mounted resources easier to use.
- `setup/zsh/zshrc` adds this directory to `PATH`.

`catalog/`
- Source of truth for optional resources to fetch.
- Keep URLs, profiles, targets, and checksums here.

## What Should Not Live Here

- Engagement output
- Customer data
- Credentials, tokens, VPN files, private keys
- Huge archives mirrored from upstream just because they exist
- Unpinned `latest` binaries that nobody reviews
- Tools that already belong in `nihil-images`

If something must always be present in every container, it probably belongs in `nihil-images`, not here.

If something is specific to one engagement, it belongs in the mounted workspace or in `nihil-history`, not here.

## Working Rule

Start text-first.

Before committing a new resource, ask:

1. Is this shared across engagements?
2. Is this small enough and stable enough to live in Git?
3. If not, can it be declared in `catalog/resources.toml` and fetched on demand?
4. Should this really be baked into an image instead?

## First Use

```bash
python3 scripts/sync.py validate
python3 scripts/sync.py list
```

No resource is enabled by default yet.
Curate the catalog first, then enable only what you want to sync locally.
