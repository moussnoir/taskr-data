# taskr-data

Base mondiale des commerces de services utilisée par l'application Taskr, reconstruite automatiquement chaque semaine (GitHub Actions) et publiée sur GitHub Pages.

- Source : [Overture Maps Foundation](https://overturemaps.org) — thème *places*, licence CDLA-Permissive-2.0 et sources partenaires ([attribution](https://docs.overturemaps.org/attribution/)).
- Filtres : métiers de services (artisans, beauté, cours, réparation, événementiel…), confiance ≥ 0,6, lieux non signalés fermés.
- Format : `index.json` (liste des carrés) + `t/<lat>_<lng>.json` (carrés de 1°).
