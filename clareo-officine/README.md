# Clareo Officine

Site **Audit IA — Pharmacies d’Officine** (by Clareo Solutions).

Brochure interactive de cadrage terrain : 28 questions, 7 thèmes, envoi vers Notion
(base *Réponses Audit IA Officine*).

Source de vérité du contenu : page Notion
[Audit IA — Pharmacies d’Officine](https://www.notion.so/3b731487ede8817f9c63e942c257752f).

## Lancer en local

```bash
cd clareo-officine
python3 -m http.server 4173
```

## Déploiement Netlify

Publish directory : `.` (voir `netlify.toml`).

Pour brancher l’envoi direct Notion :

```js
localStorage.setItem('AUDIT_NOTION_API_URL', 'https://…')
```
