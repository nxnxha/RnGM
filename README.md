# Miri Rencontre — Dossier prêt (IDs pré-remplis)

## Ce qui est déjà mis
- **GUILD_ID** = 1382730341944397967
- **ROLE_ACCESS** = 1401403405729267762
- **CH_GIRLS** = 1400520391793053841
- **CH_BOYS** = 1400520396557521058
- **CH_SPEED** = 1402665906546413679
- **CH_LOGS** = 1403154919913033728
- **CH_WELCOME** = 0 (mets un ID si tu veux l'embed d'accueil auto)

Le **token** Discord n'est pas dans le code (sécurité). Mets-le dans Railway → Variables → `DISCORD_TOKEN`.

## Déploiement (Railway, via Dockerfile)
1) Crée un **Empty Project**. Supprime tout ancien fichier Node.
2) Upload ces 3 fichiers: `Dockerfile`, `miri_rencontre.py`, `requirements.txt`.
3) Variables d'env:
   - `DISCORD_TOKEN` (obligatoire)
   - (optionnel) pour override : `GUILD_ID`, `ROLE_ACCESS`, `CH_GIRLS`, `CH_BOYS`, `CH_SPEED`, `CH_LOGS`, `CH_WELCOME`, `FIRST_MSG_LIMIT`, `DATA_FILE`
4) Rebuild **without cache**.
5) Le bot doit afficher dans les logs: `✅ Connecté en tant que ...`.
