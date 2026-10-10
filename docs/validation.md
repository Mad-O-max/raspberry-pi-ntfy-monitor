# Oplevering — 2026-10-10

Het project is gebouwd als één daemon met een gestructureerde journald-lezer,
afzonderlijke parsers, begrensde SSH-aggregatie, achtergrondmetingen en centrale
ntfy-aflevering. De hoofdthread beheert persistente toestand en waarschuwingen.
Alle veertien gevraagde monitorcategorieën zijn geïmplementeerd, met de hieronder
beschreven beperkingen. Er zijn geen systeeminstellingen gewijzigd, geen echte
notificaties verstuurd en geen GitHub-wijzigingen gedaan.

## Controles

- 56 offline pytest-tests geslaagd op Python 3.13.5 / Debian 13 / aarch64.
- `ruff check .` en `ruff format --check .`: geslaagd.
- `python -m build`: sdist en wheel succesvol gebouwd.
- CLI-configuratiecontrole en diagnostics: geslaagd met een fictief lokaal topic.
- Daemonintegratietest: SIGTERM schrijft een nette clean-exit-marker.
- Originele systemd-unitcontrole meldt het ontbrekende installatiepad
  `/opt/pi-monitor/.venv/bin/python`. Syntaxcontrole met uitsluitend dat pad
  tijdelijk vervangen door `/usr/bin/python3`: exitcode 0.
- Hardwarelezingen: thermal_zone0 heet cpu-thermal, vcgencmd levert een bitmasker,
  en de lokale read-only APT-helper levert geldige tellingen.
- Bestanden, staged diff en bestaande Git-blobs gecontroleerd op herkenbare
  credentials, privésleutels en onnodige publieke IPv4-adressen: niets gevonden.
  Configuratienamen en fictieve testtokens zijn verwachte tekstmatches.
- CI voor Python 3.11/3.12/3.13 is geconfigureerd; GitHub Actions en een echte
  Ubuntu-installatie zijn nog niet uitgevoerd. Geen live ntfy-aflevering getest.

## Installatie en benodigde gegevens

Zie de exacte opdrachten in [README](../README.md#install-on-ubuntu--raspberry-pi).
De lokale ontwikkelomgeving staat in `.venv`. Vereist vóór activering:

1. Eigen ntfy-topic; server-URL en token indien nodig.
2. Controle van kritieke services, schijfpaden en de temperatuurzone.
3. Leesrechten op journald en de firmware-interface voor de servicegebruiker.
4. Verificatie dat fail2ban-banregels daadwerkelijk in journald terechtkomen.

De service is voorbereid, niet geïnstalleerd of ingeschakeld. Het programma leest
Ubuntu/Debian APT-metadata; het installeert of ververst geen pakketten. Vorige
rebootredenen blijven heuristisch. Meldingen zijn best effort: begrensde wachtrijen
kunnen oude meldingen laten vallen. fail2ban-logbestanden worden niet gevolgd;
Ubuntu Pro/ESM-securityclassificatie is niet volledig ondersteund.

## Git

Branch: `main`. Auteursgegevens zijn alleen lokaal voor deze repository ingesteld
zoals opgegeven. De broncode en documentatie zijn in afzonderlijke commits vastgelegd.
Na deze opleveringscommit hoort `git status --short` leeg te zijn. Het oorspronkelijke
`prompt_ntfy_monitor.txt`, de venv, caches, lokale toestand en buildartefacten zijn
bewust uitgesloten van Git. De opgegeven auteursmail is zichtbaar in commitmetadata.

Een volgende inhoudelijke commit kan na echte deploymentvalidatie zijn:
`docs: record first Raspberry Pi deployment validation`.
Er is geen GitHub-remote aangemaakt. Publiceer pas na de controles in README:

```bash
git status
git diff --cached
git grep -n -I -E 'Bearer |PI_NTFY_TOKEN|PI_NTFY_TOPIC|PRIVATE KEY'
gh auth status
gh repo create raspberry-pi-ntfy-monitor --public --source=. --remote=origin
git push -u origin main
```

## Definitieve projectboom (Git-bestanden)

```text
raspberry-pi-ntfy-monitor/
├── .github/
│   └── workflows/
│       └── tests.yml
├── .gitignore
├── .vscode/
│   ├── extensions.json
│   └── settings.json
├── AGENTS.md
├── CHANGELOG.md
├── LICENSE
├── MANIFEST.in
├── README.md
├── config/
│   └── pi-monitor.env.example
├── docs/
│   ├── architecture.md
│   ├── configuration.md
│   ├── troubleshooting.md
│   └── validation.md
├── pyproject.toml
├── src/
│   └── pi_monitor/
│       ├── __init__.py
│       ├── __main__.py
│       ├── app.py
│       ├── apt_helper.py
│       ├── config.py
│       ├── journal.py
│       ├── logging_setup.py
│       ├── models.py
│       ├── monitors/
│       │   ├── __init__.py
│       │   ├── boot.py
│       │   ├── disk.py
│       │   ├── fail2ban.py
│       │   ├── filesystem.py
│       │   ├── load.py
│       │   ├── memory.py
│       │   ├── network.py
│       │   ├── public_ip.py
│       │   ├── services.py
│       │   ├── ssh.py
│       │   ├── temperature.py
│       │   ├── threshold.py
│       │   ├── throttling.py
│       │   └── updates.py
│       ├── notifier.py
│       └── state.py
├── systemd/
│   └── pi-monitor.service
└── tests/
    ├── test_additional.py
    ├── test_core.py
    ├── test_foundation.py
    ├── test_runtime.py
    └── test_security.py
```
