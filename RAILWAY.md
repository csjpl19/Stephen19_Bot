# Déployer Stephen19 Bot sur Railway

Le bot fonctionne comme un processus Python permanent qui interroge Telegram
(long polling). Il n'a besoin ni de domaine public, ni de serveur HTTP, ni de
base de données. Les fichiers téléchargés sont temporaires.

## 1. Créer le service depuis GitHub

1. Se connecter à [Railway](https://railway.com/dashboard).
2. Choisir un abonnement Hobby pour le fonctionnement continu avec redémarrage
   `Always`. Les crédits d'essai ne constituent pas un hébergement permanent.
3. Créer un projet, choisir **Deploy from GitHub repo**, puis sélectionner
   `csjpl19/Stephen19_Bot`, branche `main`.
4. Si Railway demande l'accès à GitHub, autoriser uniquement le dépôt nécessaire.
5. Garder la racine du dépôt comme répertoire du service. Railway détecte le
   `Dockerfile`, qui installe Python, FFmpeg/FFprobe, Deno et les dépendances.
   Les tests sont exécutés pendant la construction ; un échec bloque l'image.

## 2. Configurer les variables

Dans **Variables** du service :

| Variable | Valeur |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Le token BotFather du bot, saisi uniquement dans Railway. |
| `ALLOWED_USER_IDS` | Facultatif : identifiants numériques séparés par des virgules. Vide = accès à tous en privé. |
| `RAILWAY_DEPLOYMENT_OVERLAP_SECONDS` | `0` pour limiter le chevauchement des versions lors d'un déploiement. |
| `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` | `30` pour laisser à l'ancienne version le temps de s'arrêter. |

Ne pas importer `.env` ou `.env.example` dans GitHub. Ces deux fichiers locaux
contiennent une configuration privée et sont exclus de Git et du contexte Docker.
Le token n'est pas nécessaire pendant la construction de l'image.

## 3. Réglages du service

| Réglage | Valeur à vérifier |
|---|---|
| Build | Dockerfile à la racine, détection automatique. |
| Start command | Laisser vide : le Dockerfile démarre `python -u bot.py`. |
| Serverless / App Sleeping | **Désactivé**. |
| Restart policy | **Always** (abonnement payant requis). |
| Replicas | **1 au total**, dans une seule région. |
| Healthcheck HTTP | Aucun : le bot n'expose pas de route HTTP. |
| Public networking / domaine | Aucun nécessaire. |
| Cron | Aucun : le processus doit tourner en continu. |
| Volume / base de données | Aucun nécessaire. |
| Ressources | Pour commencer, prévoir jusqu'à 2 vCPU et au moins 2 Go de RAM ; ajuster après observation des conversions. |
| Environnements de prévisualisation | Ne pas déployer de copie avec le même token Telegram. |

Le plafond des ressources ne représente pas une réservation et ne fixe pas le
montant de la facture. Railway facture la consommation. Configurer une alerte de
dépenses ; un plafond financier qui arrête le service interrompt aussi le bot.

Les anciens fichiers `railway.json` et `railway.toml` ne sont plus le mécanisme
recommandé pour les nouveaux services. Ce projet utilise le Dockerfile et les
réglages du service. Il n'a pas besoin d'un SDK d'infrastructure supplémentaire.

## 4. Lancer et vérifier

1. Arrêter l'instance locale avec Ctrl+C **avant** de lancer celle de Railway.
   Un seul processus doit utiliser ce token en long polling.
2. Appliquer les variables et déployer. Un premier échec « token manquant » se
   résout en ajoutant la variable, puis en redéployant.
3. Vérifier les journaux de construction, puis les journaux d'exécution.
4. Envoyer `/start` dans Telegram, puis essayer un titre musical et un lien public
   de chaque plateforme utilisée, avec des contenus autorisés.
5. Fermer le terminal local et refaire un essai après au moins 15 minutes.
6. Contrôler la RAM, le CPU et le trafic pendant une conversion vidéo.

Le statut de déploiement Railway indique que le processus a démarré ; il ne
garantit pas la disponibilité de YouTube, Instagram, TikTok ou Facebook.
Les requêtes aux plateformes doivent être testées depuis l'adresse IP Railway.

Le bot conserve les messages Telegram en attente au redémarrage. Une demande
déjà en cours peut toutefois être interrompue lors d'un redéploiement : attendre
la fin des conversions avant une mise à jour et renvoyer la demande si nécessaire.
Les temporaires ne sont pas persistants et aucune file durable n'est implémentée.

## 5. Mettre à jour

Après un push sur `main`, Railway peut reconstruire le service depuis GitHub.
Conserver une seule instance et éviter les mises à jour pendant un téléchargement.
Un redéploiement sans cache permet de réinstaller les dépendances récentes,
notamment yt-dlp, lorsque les plateformes changent.

Pour construire et vérifier localement l'image si Docker est disponible :

```powershell
docker build -t stephen19-bot .
docker run --rm --network none stephen19-bot python -m unittest discover -s tests -v
```

Cette vérification ne démarre pas le bot et n'utilise aucun token.

Références : [Dockerfiles](https://docs.railway.com/builds/dockerfiles),
[Serverless](https://docs.railway.com/deployments/serverless),
[redémarrages](https://docs.railway.com/deployments/restart-policy),
[arrêt des déploiements](https://docs.railway.com/deployments/deployment-teardown),
[Infrastructure as Code](https://docs.railway.com/infrastructure-as-code).
