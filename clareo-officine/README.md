# Clareo Officine

Site vitrine de **Clareo Officine** (by Clareo Solutions) — accompagnement IA pour les pharmacies d'officine.

## Contenu

Landing page unique :

- promesse titulaire / LGO
- cas d'usage prioritaires (audit LGO, planning, rejets, rédaction, remises, factures)
- méthode de triage (LGO dormant → IA sur exports → outil marché → custom)
- zones de non-automatisation (interactions, fausses ordonnances)
- formulaire d'audit (ouvre un `mailto:` vers Clareo Solutions)

## Lancer en local

```bash
cd clareo-officine
python3 -m http.server 4173
```

Puis ouvrir `http://localhost:4173`.

## Déploiement Netlify

Dossier racine du site : `clareo-officine/`.

- Build command : _(vide)_
- Publish directory : `.` (ou `clareo-officine` si le site Netlify pointe sur le dépôt entier)

Le fichier `netlify.toml` de ce dossier fixe le publish directory à `.`.
